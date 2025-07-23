import logging

from fastapi import APIRouter, Depends, HTTPException, status
from google.api_core import exceptions as google_exceptions

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.nutrition_target import NutritionTarget
from app.models.user import User
from google.cloud.firestore_v1.async_client import AsyncClient

logger = logging.getLogger(__name__)
router = APIRouter()


@router.put(
    "/targets",
    response_model=NutritionTarget,
    status_code=status.HTTP_200_OK,
)
async def set_user_nutrition_targets(
    targets: NutritionTarget,
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Sets or updates the daily nutritional targets for the authenticated user.

    This endpoint receives a JSON object with one or more nutritional targets.
    Any fields provided will be updated, and any omitted fields will remain
    unchanged in the database.
    """
    logger.info(f"User '{current_user.uid}' attempting to set nutrition targets.")
    targets_to_update = targets.model_dump(exclude_unset=True, by_alias=True)

    if not targets_to_update:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body cannot be empty. Please provide at least one target to update.",
        )

    user_doc_ref = db.collection("users").document(current_user.uid)
    data_to_save = {"nutritionTargets": targets_to_update}

    try:
        await user_doc_ref.set(data_to_save, merge=True)
        logger.info(f"Successfully updated targets for user '{current_user.uid}'.")
        updated_doc = await user_doc_ref.get()
        updated_targets = updated_doc.to_dict().get("nutritionTargets", {})
        return NutritionTarget(**updated_targets)

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error while setting targets for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while setting targets.",
        )


@router.get(
    "/targets",
    response_model=NutritionTarget,
    status_code=status.HTTP_200_OK,
)
async def get_user_nutrition_targets(
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Retrieves the daily nutritional targets for the authenticated user.

    If no targets are explicitly set, an empty NutritionTarget object will be returned.
    """
    logger.info(f"User '{current_user.uid}' attempting to retrieve nutrition targets.")

    user_doc_ref = db.collection("users").document(current_user.uid)

    try:
        user_doc = await user_doc_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            targets_data = user_data.get("nutritionTargets", {})
            logger.info(
                f"Successfully retrieved targets for user '{current_user.uid}'."
            )
            return NutritionTarget(**targets_data)
        else:
            logger.info(
                f"No document found for user '{current_user.uid}'. Returning default targets."
            )
            return (
                NutritionTarget()
            )  # Return an empty NutritionTarget if user document doesn't exist or has no targets
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error while retrieving targets for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while retrieving targets.",
        )
