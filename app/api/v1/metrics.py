import logging
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.meal import MealDB
from app.models.user import User
from app.schemas.daily_summary import DailySummary
from meal_generator import NutrientProfile, MealType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/summary",
    response_model=DailySummary,
    response_model_by_alias=True,
)
async def get_daily_nutrition_summary(
    date: date = Query(
        None,
        description="The date for the summary in YYYY-MM-DD format. Defaults to today (UTC).",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Provides a daily nutritional summary for the authenticated user.

    The summary is calculated by querying all meals for the user within the
    24-hour UTC window of the target date and aggregating their nutrient profiles.
    Malformed meal records in the database are logged and skipped.
    """
    target_date = date if date else datetime.now(timezone.utc).date()
    logger.info(
        f"Request for daily nutrition summary: user='{current_user.uid}', date={target_date}"
    )

    start_of_day_utc = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    end_of_day_utc = datetime.combine(target_date, time.max, tzinfo=timezone.utc)

    try:
        meals_ref = db.collection("meals")
        query = (
            meals_ref.where(filter=FieldFilter("uid", "==", current_user.uid))
            .where(filter=FieldFilter("createdAt", ">=", start_of_day_utc))
            .where(filter=FieldFilter("createdAt", "<=", end_of_day_utc))
        )
        docs = await query.get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore query failed for user '{current_user.uid}' on date {target_date}: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while fetching the daily summary.",
        )

    profiles = []
    malformed_docs_count = 0
    meal_count = 0
    snack_count = 0
    beverage_count = 0
    for doc in docs:
        try:
            meal = MealDB.model_validate(doc.to_dict())
            match meal.type:
                case MealType.MEAL:
                    meal_count += 1
                case MealType.SNACK:
                    snack_count += 1
                case MealType.BEVERAGE:
                    beverage_count += 1
            if meal.nutrient_profile:
                profiles.append(meal.nutrient_profile)
        except ValidationError as e:
            malformed_docs_count += 1
            logger.warning(
                f"Skipping malformed meal document '{doc.id}' for user '{current_user.uid}'. Reason: {e}",
                exc_info=True,
            )

    if malformed_docs_count > 0:
        logger.warning(
            f"Found and skipped {malformed_docs_count} malformed meal documents for user '{current_user.uid}'."
        )

    total_nutrients = sum(profiles, NutrientProfile())

    summary = DailySummary(
        meal_count=meal_count,
        snack_count=snack_count,
        beverage_count=beverage_count,
        **total_nutrients.as_dict(),
    )

    logger.info(
        f"Aggregated {len(profiles)} valid meals for user '{current_user.uid}' on {target_date}."
    )

    return summary
