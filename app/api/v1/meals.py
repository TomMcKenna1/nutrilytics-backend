import logging
import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud.firestore_v1.base_client import BaseClient
from firebase_admin import firestore

from app.api.deps import get_current_user, get_redis_client
from app.db.firebase import get_firestore_client
from app.models.user import User
from app.schemas.meal import MealDraft, MealGenerationStatus, MealResponse, MealSaveFromDraftRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=MealResponse)
async def save_meal_from_draft(
    request: MealSaveFromDraftRequest,
    current_user: User = Depends(get_current_user),
    db: BaseClient = Depends(get_firestore_client),
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

    draft_json = await redis_client.get(draft_id)
    if not draft_json:
        logger.warning(f"Draft '{draft_id}' not found for user '{current_user.uid}'.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found."
        )

    draft = MealDraft.model_validate_json(draft_json)
    if draft.uid != current_user.uid:
        logger.warning(
            f"User '{current_user.uid}' forbidden from accessing draft '{draft_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft.",
        )
    if draft.status != MealGenerationStatus.COMPLETE or not draft.meal:
        logger.warning(f"Draft '{draft_id}' is not complete and cannot be saved.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft is not complete and cannot be saved.",
        )

    meal_data_to_save = draft.meal.model_dump()
    meal_data_to_save["uid"] = current_user.uid
    meal_data_to_save["createdAt"] = firestore.SERVER_TIMESTAMP

    try:
        doc_ref = db.collection("meals").document()
        doc_ref.set(meal_data_to_save)
        logger.info(
            f"Successfully saved meal '{doc_ref.id}' to Firestore for user '{current_user.uid}'."
        )

        await redis_client.delete(draft_id)
        logger.info(f"Successfully deleted draft '{draft_id}' from Redis.")

        new_meal_doc = doc_ref.get()
        return MealResponse(id=new_meal_doc.id, **new_meal_doc.to_dict())

    except Exception as e:
        logger.error(
            f"Failed during DB operations for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while saving the meal.",
        )


@router.get("/{meal_id}", response_model=MealResponse)
async def get_meal_by_id(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    db: BaseClient = Depends(get_firestore_client),
) -> MealResponse:
    """
    Retrieves a specific meal by its ID from Firestore, checking for ownership.
    """
    logger.info(f"User '{current_user.uid}' requesting meal '{meal_id}'.")
    try:
        doc_ref = db.collection("meals").document(meal_id)
        meal_doc = doc_ref.get()

    except Exception as e:
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
    return MealResponse(id=meal_doc.id, **meal_data)
