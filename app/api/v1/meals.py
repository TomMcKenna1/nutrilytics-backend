
import logging
from typing import Optional

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.query import Query as FirestoreQuery
from firebase_admin import firestore

from app.api.deps import get_current_user, get_redis_client
from app.db.firebase import get_firestore_client
from app.models.meal_response import MealResponse
from app.models.meal_draft import MealDraft, MealGenerationStatus
from app.models.user import User
from app.schemas.meal_request import MealListResponse, MealSaveFromDraftRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=MealResponse)
async def save_meal_from_draft(
    request: MealSaveFromDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> MealResponse:
    """
    Saves a new meal by validating and promoting a completed meal draft
    from Redis to a permanent record in Firestore.

    Args:
        request: The request body containing the draftId.
        current_user: The authenticated user, injected by dependency.
        db: The Firestore client, injected by dependency.
        redis_client: The Redis client, injected by dependency.

    Raises:
        HTTPException(404): If the meal draft is not found in Redis.
        HTTPException(403): If the user is not authorized to access the draft.
        HTTPException(409): If the draft is not in a 'complete' state.

    Returns:
        The newly created and saved meal object.
    """
    draft_id = request.draft_id
    logger.info(
        f"User '{current_user.uid}' attempting to save meal from draft '{draft_id}'."
    )

    # Fetch and validate draft from Redis
    try:
        draft_json = await redis_client.get(draft_id)
        if not draft_json:
            logger.warning(f"Draft '{draft_id}' not found for user '{current_user.uid}'.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found."
            )
        draft = MealDraft.model_validate_json(draft_json)

    except redis.RedisError as e:
        logger.error(
            f"Redis error fetching draft '{draft_id}' for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A cache server error occurred.",
        )

    # Authorisation and status checks ---
    if draft.uid != current_user.uid:
        logger.warning(
            f"User '{current_user.uid}' forbidden from accessing draft '{draft_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorised to access this draft.",
        )
    if draft.status != MealGenerationStatus.COMPLETE or not draft.meal:
        logger.warning(f"Draft '{draft_id}' is not complete and cannot be saved.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft is not complete and cannot be saved.",
        )

    # Save to Firestore and cleanup
    meal_data_to_save = draft.meal.model_dump()
    meal_data_to_save["uid"] = current_user.uid
    meal_data_to_save["createdAt"] = firestore.SERVER_TIMESTAMP

    doc_ref = db.collection("meals").document()
    try:
        await doc_ref.set(meal_data_to_save)
        logger.info(
            f"Successfully saved meal '{doc_ref.id}' to Firestore for user '{current_user.uid}'."
        )
        await redis_client.delete(draft_id)
        logger.info(f"Successfully deleted draft '{draft_id}' from Redis.")

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error while saving meal from draft '{draft_id}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while saving the meal.",
        )
    except redis.RedisError as e:
        logger.critical(
            f"CRITICAL: Failed to delete draft '{draft_id}' after saving meal '{doc_ref.id}'. Manual cleanup may be required. Error: {e}",
            exc_info=True,
        )

    # Invalidate cache for latest meals
    try:
        keys_to_delete = [
            key
            async for key in redis_client.scan_iter(
                f"latest_meals_v*:{current_user.uid}:*"
            )
        ]
        if keys_to_delete:
            await redis_client.delete(*keys_to_delete)
            logger.info(
                f"Invalidated {len(keys_to_delete)} 'latest_meals' cache keys for user '{current_user.uid}'."
            )
    except redis.RedisError as e:
        logger.error(
            f"Failed to invalidate cache for user '{current_user.uid}'. Error: {e}",
            exc_info=True,
        )

    # Return meal
    try:
        new_meal_doc = await doc_ref.get()
        return MealResponse(id=new_meal_doc.id, **new_meal_doc.to_dict())
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Failed to fetch newly created meal '{doc_ref.id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Meal was saved, but could not be retrieved.",
        )


@router.get(
    "/",
    response_model=MealListResponse,
    summary="Get Meals Collection",
    description="Retrieves a collection of meals. Use '?sort=latest' to get the most recent meals with pagination.",
)
async def get_meals_async(
    response: Response,
    sort: Optional[str] = Query(
        None, description="Sort order. Use 'latest' to get the most recent meals."
    ),
    limit: int = Query(10, ge=1, le=20, description="Number of meals to return per page."),
    next: Optional[str] = Query(
        None, description="The document ID of the last meal from the previous page."
    ),
    user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
    db: AsyncClient = Depends(get_firestore_client),
) -> MealListResponse:
    if sort != "latest":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported query. Please use '?sort=latest' to fetch the latest meals.",
        )

    start_key = next if next else "first"
    cache_key = f"latest_meals_v5:{user.uid}:{limit}:{start_key}"

    # Check cache
    try:
        if cached_data := await redis_client.get(cache_key):
            logger.info(f"Cache hit for key: {cache_key}")
            response.headers["X-Cache"] = "hit"
            return MealListResponse.model_validate_json(cached_data)
    except redis.RedisError as e:
        logger.error(f"Redis error: {e}", exc_info=True)

    response.headers["X-Cache"] = "miss"
    logger.info(f"Cache miss for key: {cache_key}")

    # Query Firestore
    try:
        meals_collection = db.collection("meals")
        query = (
            meals_collection.where(filter=FieldFilter("uid", "==", user.uid))
            .order_by("createdAt", direction=FirestoreQuery.DESCENDING)
            .order_by("__name__", direction=FirestoreQuery.DESCENDING)
        )

        if next:
            if last_doc_snapshot := await meals_collection.document(next).get():
                query = query.start_after(last_doc_snapshot)
            else:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid 'next'. Document not found.",
                )

        docs = [doc async for doc in query.limit(limit).stream()]

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore query failed for user '{user.uid}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while fetching meals.",
        )

    # Process and Return Response
    meals_list = [doc.to_dict() | {"id": doc.id} for doc in docs]
    next_page_cursor = docs[-1].id if len(docs) == limit else None
    final_response = MealListResponse(meals=meals_list, next=next_page_cursor)

    # Cache new result
    try:
        await redis_client.set(cache_key, final_response.model_dump_json(), ex=300)
    except redis.RedisError as e:
        logger.error(f"Redis set error for key '{cache_key}': {e}", exc_info=True)

    return final_response


@router.get("/{meal_id}", response_model=MealResponse)
async def get_meal_by_id(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
) -> MealResponse:
    """
    Retrieves a specific meal by its ID from Firestore, checking for ownership.
    """
    logger.info(f"User '{current_user.uid}' requesting meal '{meal_id}'.")
    try:
        doc_ref = db.collection("meals").document(meal_id)
        meal_doc = await doc_ref.get()

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error while fetching meal '{meal_id}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while fetching the meal.",
        )

    if not meal_doc.exists:
        logger.warning(f"Meal '{meal_id}' not found for user '{current_user.uid}'.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
        )

    meal_data = meal_doc.to_dict()
    if meal_data.get("uid") != current_user.uid:
        logger.warning(
            f"User '{current_user.uid}' forbidden from accessing meal '{meal_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this meal",
        )

    logger.info(
        f"Successfully retrieved meal '{meal_id}' for user '{current_user.uid}'."
    )
    print(meal_doc.id)
    return MealResponse(id=meal_doc.id, **meal_data)