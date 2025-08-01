import logging
from datetime import datetime, timedelta, timezone

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
    description="Creates a basic user record in Firestore after initial auth sign-up.",
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

        user_data = {
            "email": current_user.email,
            "name": current_user.name,
            "createdAt": datetime.now(timezone.utc),
            "onboardingComplete": False,
            "logStreak": 0,
            "lastActivityAt": None,
            "currentWeightKg": None,
            "profile": None,
            "nutritionTargets": {},
        }
        await user_doc_ref.set(user_data)
        logger.info(f"Successfully created record for user '{current_user.uid}'.")

        created_doc = await user_doc_ref.get()
        return UserInDB(uid=created_doc.id, **created_doc.to_dict())

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
    description="Sets initial profile and targets, and marks onboarding as complete.",
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
            "currentWeightKg": payload.profile.weight_kg,
        }

        await user_doc_ref.update(update_data)
        logger.info(f"Successfully onboarded user '{current_user.uid}'.")

        updated_doc = await user_doc_ref.get()
        return UserInDB(uid=updated_doc.id, **updated_doc.to_dict())

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error during onboarding for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )


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
    logger.info(f"Retrieving profile for user '{current_user.uid}'.")
    user_doc_ref = db.collection("users").document(current_user.uid)
    try:
        doc = await user_doc_ref.get()
        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found."
            )
        return UserInDB(uid=doc.id, **doc.to_dict())
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
    """Updates non-weight fields in the user's profile (sex, age, height, etc.)."""
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
        return UserInDB(uid=updated_doc.id, **updated_doc.to_dict())
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


@router.post(
    "/streak/log",
    response_model=UserInDB,
    status_code=status.HTTP_200_OK,
    summary="Log Daily Activity to Update Streak",
    description="Updates the user's daily streak based on their last activity. This should be called when a user performs a loggable action, like submitting a meal.",
)
async def update_user_streak(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Checks the user's last activity date and updates their daily streak.
    - If the last log was yesterday, the streak is incremented.
    - If the last log was before yesterday, the streak is reset to 1.
    - If this is the first log, the streak starts at 1.
    - If a log was already made today, the streak is unchanged.
    """
    logger.info(f"User '{current_user.uid}' attempting to update streak.")
    user_doc_ref = db.collection("users").document(current_user.uid)

    try:
        doc = await user_doc_ref.get()
        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User record not found. Cannot update streak.",
            )

        user = UserInDB(**doc.to_dict())
        now = datetime.now(timezone.utc)
        today = now.date()

        new_streak = user.log_streak

        if user.last_activity_at is None:
            # First-ever log for the user
            new_streak = 1
        else:
            last_activity_date = user.last_activity_at.date()

            if last_activity_date < today:
                # This is the first log of a new day
                if last_activity_date == today - timedelta(days=1):
                    # Last log was yesterday, so increment the streak
                    new_streak += 1
                else:
                    # Last log was before yesterday, so the streak is broken
                    new_streak = 1
            # If last_activity_date == today, do nothing to the streak.

        update_data = {
            "logStreak": new_streak,
            "lastActivityAt": now,
        }

        await user_doc_ref.update(update_data)
        logger.info(
            f"Successfully updated streak for user '{current_user.uid}' to {new_streak}."
        )

        updated_doc = await user_doc_ref.get()
        return UserInDB(**updated_doc.to_dict())

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error updating streak for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while updating the streak.",
        )
