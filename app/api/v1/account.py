import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.nutrition_target import NutritionTarget
from app.schemas.onboarding_request import OnboardingRequest
from app.models.profile import UserProfileBase
from app.models.user import AuthUser, UserInDB

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/",
    response_model=UserInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Create User Record",
    description="Creates a basic user record in Firestore after initial auth sign-up. This marks the user's status as 'onboarding incomplete'.",
)
async def create_user_record(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    logger.info(f"Attempting to create record for user '{current_user.uid}'.")
    user_doc_ref = db.collection("users").document(current_user.uid)

    try:
        if (await user_doc_ref.get()).exists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A record for this user already exists.",
            )

        # Create a user with no profile/targets and onboarding set to false
        user_data = {
            "uid": current_user.uid,
            "email": current_user.email,
            "name": current_user.name,
            "createdAt": datetime.now(timezone.utc),
            "profile": None,
            "nutritionTargets": {},
            "onboardingComplete": False,
        }

        await user_doc_ref.set(user_data)
        logger.info(f"Successfully created record for user '{current_user.uid}'.")

        created_doc = await user_doc_ref.get()
        return UserInDB(**created_doc.to_dict())

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error creating record for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )


@router.post(
    "/onboard",
    response_model=UserInDB,
    status_code=status.HTTP_200_OK,
    summary="Complete User Onboarding",
    description="Sets the user's initial profile and nutrition targets, and marks onboarding as complete.",
)
async def onboard_user(
    payload: OnboardingRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    logger.info(f"User '{current_user.uid}' attempting to complete onboarding.")
    user_doc_ref = db.collection("users").document(current_user.uid)

    try:
        doc = await user_doc_ref.get()
        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User record not found. Please create a record first.",
            )
        if doc.to_dict().get("onboardingComplete"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User has already completed onboarding.",
            )

        update_data = {
            "profile": payload.profile.model_dump(by_alias=True),
            "nutritionTargets": payload.nutrition_targets.model_dump(
                by_alias=True, exclude_unset=True
            ),
            "onboardingComplete": True,
        }

        await user_doc_ref.update(update_data)
        logger.info(f"Successfully onboarded user '{current_user.uid}'.")

        updated_doc = await user_doc_ref.get()
        return UserInDB(**updated_doc.to_dict())

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error during onboarding for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )


# The GET, PUT /, and PUT/GET /targets endpoints remain unchanged as they are still useful
# for retrieving or making partial updates after onboarding is complete.


@router.get(
    "/",
    response_model=UserInDB,
    status_code=status.HTTP_200_OK,
    summary="Get User Profile",
)
async def get_user_profile(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Retrieves the full profile for the authenticated user."""
    # This function remains valid
    logger.info(f"Retrieving profile for user '{current_user.uid}'.")
    user_doc_ref = db.collection("users").document(current_user.uid)
    try:
        doc = await user_doc_ref.get()
        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found."
            )
        return UserInDB(**doc.to_dict())
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error getting profile for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )


@router.put(
    "/",
    response_model=UserInDB,
    status_code=status.HTTP_200_OK,
    summary="Update User Profile",
)
async def update_user_profile(
    profile_update: UserProfileBase,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Updates one or more fields in the user's profile (sex, age, height, etc.)."""
    # This function remains valid
    logger.info(f"Updating profile for user '{current_user.uid}'.")
    update_data = profile_update.model_dump(exclude_unset=True, by_alias=True)
    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body cannot be empty.",
        )

    user_doc_ref = db.collection("users").document(current_user.uid)
    try:
        await user_doc_ref.update({f"profile.{k}": v for k, v in update_data.items()})
        logger.info(f"Successfully updated profile for '{current_user.uid}'.")
        updated_doc = await user_doc_ref.get()
        return UserInDB(**updated_doc.to_dict())
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error updating profile for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )


@router.put(
    "/targets",
    response_model=NutritionTarget,
    status_code=status.HTTP_200_OK,
    summary="Set Nutrition Targets",
)
async def set_user_nutrition_targets(
    targets: NutritionTarget,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Sets or updates the daily nutritional targets for the authenticated user."""
    # This function remains valid
    logger.info(f"User '{current_user.uid}' setting nutrition targets.")
    targets_to_update = targets.model_dump(exclude_unset=True, by_alias=True)

    if not targets_to_update:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body cannot be empty.",
        )

    user_doc_ref = db.collection("users").document(current_user.uid)
    try:
        await user_doc_ref.update(
            {f"nutritionTargets.{k}": v for k, v in targets_to_update.items()}
        )
        logger.info(f"Successfully updated targets for user '{current_user.uid}'.")
        updated_doc = await user_doc_ref.get()
        updated_targets = updated_doc.to_dict().get("nutritionTargets", {})
        return NutritionTarget(**updated_targets)

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error setting targets for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )


@router.get(
    "/targets",
    response_model=NutritionTarget,
    status_code=status.HTTP_200_OK,
    summary="Get Nutrition Targets",
)
async def get_user_nutrition_targets(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Retrieves the daily nutritional targets for the authenticated user."""
    # This function remains valid
    logger.info(f"User '{current_user.uid}' retrieving nutrition targets.")
    user_doc_ref = db.collection("users").document(current_user.uid)
    try:
        user_doc = await user_doc_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            targets_data = user_data.get("nutritionTargets", {})
            return NutritionTarget(**targets_data)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found."
            )
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error retrieving targets for '{current_user.uid}': {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )
