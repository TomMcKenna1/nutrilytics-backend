import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.meal import MealDB, MealGenerationStatus, ComponentType
from app.models.user import AuthUser
from app.schemas.metric_request import (
    DailySummary,
    MonthlyNutritionLog,
    MonthlySummaryResponse,
    NutrientSummary,
    SevenDayResponse,
    WeeklyBreakdown,
)
from meal_generator import NutrientProfile, MealType

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/summary",
    response_model=DailySummary,
    response_model_by_alias=True,
)
async def get_daily_nutrition_summary(
    request_date: date = Query(
        None,
        description="The date for the summary in YYYY-MM-DD format. Defaults to today (UTC).",
        alias="date",
    ),
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Provides a daily nutritional summary for the authenticated user.

    The summary is calculated by querying all meals for the user within the
    24-hour UTC window of the target date and aggregating their nutrient profiles.
    Only meals with a 'complete' status are included. Malformed or incomplete
    meal records in the database are logged and skipped.
    """
    target_date = request_date if request_date else datetime.now(timezone.utc).date()
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
            .where(
                filter=FieldFilter("status", "==", MealGenerationStatus.COMPLETE.value)
            )
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
            if meal.data:
                if meal.data.type == MealType.MEAL:
                    meal_count += 1
                elif meal.data.type == MealType.SNACK:
                    snack_count += 1

                if meal.data.components:
                    for component in meal.data.components:
                        if component.type == ComponentType.BEVERAGE:
                            beverage_count += 1

                profiles.append(
                    NutrientProfile(**meal.data.nutrient_profile.model_dump())
                )
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


@router.get(
    "/weeklySummary",
    response_model=SevenDayResponse,
    response_model_by_alias=True,
)
async def get_macros_by_day(
    start_date: Optional[date] = Query(
        None,
        description="The start date for the 7-day period in YYYY-MM-DD format. Defaults to the last Monday.",
        alias="startDate",
    ),
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Provides a daily nutritional summary for a 7-day period, broken down by meal type.

    The summary is calculated by querying all 'complete' meals for the user
    within the 7-day UTC window and aggregating their nutrient profiles for each day.
    Dates with no meals will have a null value for that day.
    """
    if start_date:
        target_start_date = start_date
    else:
        today_utc = datetime.now(timezone.utc).date()
        days_since_monday = today_utc.weekday()
        target_start_date = today_utc - timedelta(days=days_since_monday)

    end_date = target_start_date + timedelta(days=6)
    start_of_period_utc = datetime.combine(
        target_start_date, time.min, tzinfo=timezone.utc
    )
    end_of_period_utc = datetime.combine(end_date, time.max, tzinfo=timezone.utc)

    try:
        meals_ref = db.collection("meals")
        query = (
            meals_ref.where(filter=FieldFilter("uid", "==", current_user.uid))
            .where(filter=FieldFilter("createdAt", ">=", start_of_period_utc))
            .where(filter=FieldFilter("createdAt", "<=", end_of_period_utc))
            .where(
                filter=FieldFilter("status", "==", MealGenerationStatus.COMPLETE.value)
            )
        )
        docs = await query.get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore query failed for user '{current_user.uid}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while fetching meal data.",
        )

    # Initialize a dictionary to hold nutrient totals for each category within each day
    daily_totals: Dict[str, Dict[str, NutrientProfile]] = {
        (target_start_date + timedelta(days=i)).isoformat(): {
            "meals": NutrientProfile(),
            "snacks": NutrientProfile(),
            "beverages": NutrientProfile(),
        }
        for i in range(7)
    }

    for doc in docs:
        try:
            meal = MealDB.model_validate(doc.to_dict())
            if meal.data and meal.data.nutrient_profile and meal.created_at:
                meal_date_str = meal.created_at.date().isoformat()
                if meal_date_str in daily_totals:
                    profile = NutrientProfile(**meal.data.nutrient_profile.model_dump())

                    # Aggregate nutrients based on the meal's top-level type
                    match meal.data.type:
                        case MealType.MEAL:
                            daily_totals[meal_date_str]["meals"] += profile
                        case MealType.SNACK:
                            daily_totals[meal_date_str]["snacks"] += profile
                        case MealType.BEVERAGE:
                            daily_totals[meal_date_str]["beverages"] += profile
        except ValidationError as e:
            logger.warning(f"Skipping malformed meal doc '{doc.id}': {e}")

    # Build the final response structure
    response_data: Dict[str, Optional[WeeklyBreakdown]] = {}
    for day_str, totals in daily_totals.items():
        is_empty = all(p == NutrientProfile() for p in totals.values())

        if is_empty:
            response_data[day_str] = None
        else:
            response_data[day_str] = WeeklyBreakdown(
                meals=(
                    NutrientSummary(**totals["meals"].as_dict())
                    if totals["meals"] != NutrientProfile()
                    else None
                ),
                snacks=(
                    NutrientSummary(**totals["snacks"].as_dict())
                    if totals["snacks"] != NutrientProfile()
                    else None
                ),
                beverages=(
                    NutrientSummary(**totals["beverages"].as_dict())
                    if totals["beverages"] != NutrientProfile()
                    else None
                ),
            )

    return SevenDayResponse(root=response_data)


@router.get(
    "/monthlySummary/{year_month}",
    response_model=MonthlySummaryResponse,
    response_model_by_alias=True,
    summary="Get Monthly Nutrition Summary",
)
async def get_monthly_nutrition_summary(
    year_month: str,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Provides a daily nutritional summary for a specified month (YYYY-MM).

    The summary is calculated by querying all 'complete' meals for the user
    within the given month and aggregating their nutrient profiles for each day.
    Months in the future are not permitted.
    """
    try:
        requested_month_dt = datetime.strptime(year_month, "%Y-%m")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid year_month format. Please use YYYY-MM.",
        )

    # Disallow requests for future months
    current_date = datetime.now(timezone.utc).date()
    first_day_of_current_month = current_date.replace(day=1)

    if requested_month_dt.date().replace(day=1) > first_day_of_current_month:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot request data for a future month.",
        )

    start_of_month = requested_month_dt.replace(tzinfo=timezone.utc)
    # Find the last day of the month
    next_month = start_of_month.replace(day=28) + timedelta(days=4)
    end_of_month = next_month - timedelta(days=next_month.day)
    end_of_period_utc = datetime.combine(
        end_of_month.date(), time.max, tzinfo=timezone.utc
    )

    try:
        meals_ref = db.collection("meals")
        query = (
            meals_ref.where(filter=FieldFilter("uid", "==", current_user.uid))
            .where(filter=FieldFilter("createdAt", ">=", start_of_month))
            .where(filter=FieldFilter("createdAt", "<=", end_of_period_utc))
            .where(
                filter=FieldFilter("status", "==", MealGenerationStatus.COMPLETE.value)
            )
        )
        docs = await query.get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore query failed for user '{current_user.uid}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database error occurred while fetching meal data.",
        )

    daily_data: Dict[str, Dict] = {}

    for doc in docs:
        try:
            meal = MealDB.model_validate(doc.to_dict())
            if meal.data and meal.created_at:
                meal_date_str = meal.created_at.date().isoformat()

                if meal_date_str not in daily_data:
                    daily_data[meal_date_str] = {
                        "meal_count": 0,
                        "nutrition": NutrientProfile(),
                        "logs": [],
                    }

                daily_data[meal_date_str]["nutrition"] += NutrientProfile(
                    **meal.data.nutrient_profile.model_dump()
                )
                if meal.data.type == MealType.MEAL:
                    daily_data[meal_date_str]["meal_count"] += 1
                    daily_data[meal_date_str]["logs"].append(meal.data.name)

        except ValidationError as e:
            logger.warning(f"Skipping malformed meal doc '{doc.id}': {e}")

    response_data = {}
    num_days = (end_of_month.date() - start_of_month.date()).days + 1
    for i in range(num_days):
        current_date = (start_of_month.date() + timedelta(days=i)).isoformat()
        if current_date in daily_data:
            day_data = daily_data[current_date]
            response_data[current_date] = MonthlyNutritionLog(
                meal_count=day_data["meal_count"],
                nutrition=NutrientSummary(**day_data["nutrition"].as_dict()),
                logs=day_data["logs"],
            )
        else:
            response_data[current_date] = None

    return MonthlySummaryResponse(root=response_data)
