import logging
from typing import Optional

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.query import Query as FirestoreQuery
from firebase_admin import firestore
from pydantic import ValidationError

from app.api.deps import get_current_user, get_redis_client
from app.db.firebase import get_firestore_client
from app.models.meal import MealCreate, MealDB
from app.models.meal_draft import Draft, MealGenerationStatus
from app.models.user import User
from app.schemas.meal_request import MealListResponse, MealSaveFromDraftRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=MealDB,
    response_model_by_alias=True,
)
async def save_meal_from_draft(
    request: MealSaveFromDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> MealDB:
    """
    Saves a new meal by validating and promoting a completed meal draft
    from Redis to a permanent MealDB record in Firestore.
    """
    draft_id = request.draft_id
    logger.info(
        f"User '{current_user.uid}' attempting to save meal from draft '{draft_id}'."
    )

    try:
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
        if not draft_json:
            logger.warning(
                f"Draft '{draft_id}' not found for user '{current_user.uid}'."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found."
            )
        draft = Draft.model_validate_json(draft_json)
    except redis.RedisError as e:
        logger.error(f"Redis error fetching draft '{draft_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A cache server error occurred.",
        )
    except ValidationError as e:
        logger.error(
            f"Draft '{draft_id}' has invalid format in Redis: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read draft data.",
        )
    if draft.uid != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorised to access this draft.",
        )
    if draft.status != MealGenerationStatus.COMPLETE or not draft.meal_draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft is not complete and cannot be saved.",
        )
    try:
        meal_to_create = MealCreate(**draft.meal_draft.model_dump())
    except ValidationError as e:
        logger.error(f"Draft '{draft_id}' data failed validation for MealCreate: {e}")
        raise HTTPException(status_code=500, detail="Invalid meal data in draft.")

    meals_collection = db.collection("meals")
    doc_ref = meals_collection.document()

    data_to_save = meal_to_create.model_dump(by_alias=True)
    data_to_save["id"] = doc_ref.id
    data_to_save["uid"] = current_user.uid
    data_to_save["submittedAt"] = draft.created_at
    data_to_save["createdAt"] = firestore.SERVER_TIMESTAMP

    try:
        await doc_ref.set(data_to_save)
        logger.info(f"Saved meal '{doc_ref.id}' for user '{current_user.uid}'.")
        await redis_client.delete(f"meal_draft:{draft_id}")
        logger.info(f"Deleted draft '{draft_id}' from Redis.")
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error saving meal from draft '{draft_id}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error while saving meal.",
        )
    except redis.RedisError as e:
        logger.critical(
            f"CRITICAL: Failed to delete draft '{draft_id}' after saving meal '{doc_ref.id}'. Manual cleanup required. Error: {e}",
            exc_info=True,
        )

    try:
        keys_to_delete = [
            key
            async for key in redis_client.scan_iter(f"meals_list:{current_user.uid}:*")
        ]
        if keys_to_delete:
            await redis_client.delete(*keys_to_delete)
            logger.info(
                f"Invalidated {len(keys_to_delete)} meal list cache keys for user '{current_user.uid}'."
            )
    except redis.RedisError as e:
        logger.error(
            f"Failed to invalidate meal list cache for user '{current_user.uid}': {e}",
            exc_info=True,
        )

    try:
        new_meal_doc = await doc_ref.get()
        return MealDB(**new_meal_doc.to_dict())
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Failed to fetch newly created meal '{doc_ref.id}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Meal was saved, but could not be retrieved.",
        )


@router.get(
    "/",
    response_model=MealListResponse,
    response_model_by_alias=True,
)
async def get_meals_list(
    response: Response,
    limit: int = Query(10, ge=1, le=20),
    next: Optional[str] = Query(None, alias="next"),
    user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncClient = Depends(get_firestore_client),
) -> MealListResponse:
    """
    Retrieves a paginated list of the user's most recent meals from Firestore.
    """
    cache_key = f"meals_list:{user.uid}:{limit}:{next or 'first'}"

    try:
        if cached_data := await redis_client.get(cache_key):
            logger.info(f"Cache hit for key: {cache_key}")
            response.headers["X-Cache"] = "hit"
            return MealListResponse.model_validate_json(cached_data)
    except redis.RedisError as e:
        logger.error(f"Redis GET error for key '{cache_key}': {e}", exc_info=True)

    response.headers["X-Cache"] = "miss"

    try:
        meals_ref = db.collection("meals")
        query = (
            meals_ref.where(filter=FieldFilter("uid", "==", user.uid))
            .order_by("createdAt", direction=FirestoreQuery.DESCENDING)
            .order_by("id", direction=FirestoreQuery.DESCENDING)
        )

        if next:
            last_doc = await meals_ref.document(next).get()
            if not last_doc.exists:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid 'next' cursor.",
                )
            query = query.start_after(last_doc)

        docs = await query.limit(limit).get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore query failed for user '{user.uid}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error fetching meals.",
        )

    meals_list = [MealDB(**doc.to_dict()) for doc in docs]

    next_page_cursor = docs[-1].id if len(docs) == limit else None
    final_response = MealListResponse(meals=meals_list, next=next_page_cursor)

    try:
        await redis_client.set(cache_key, final_response.model_dump_json(), ex=300)
    except redis.RedisError as e:
        logger.error(f"Redis SET error for key '{cache_key}': {e}", exc_info=True)

    return final_response


@router.get(
    "/{meal_id}",
    response_model=MealDB,
    response_model_by_alias=True,
)
async def get_meal_by_id(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
) -> MealDB:
    """
    Retrieves a specific meal by its ID from Firestore, checking for ownership.
    """
    logger.info(f"User '{current_user.uid}' requesting meal '{meal_id}'.")
    try:
        doc_ref = db.collection("meals").document(meal_id)
        meal_doc = await doc_ref.get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error fetching meal '{meal_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error fetching the meal.",
        )

    if not meal_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
        )

    meal_data = meal_doc.to_dict()
    if meal_data.get("uid") != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this meal",
        )

    try:
        return MealDB(**meal_data)
    except ValidationError as e:
        logger.error(f"Meal '{meal_id}' has invalid format in DB: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read meal data.",
        )
