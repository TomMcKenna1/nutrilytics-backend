from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, RootModel
from pydantic.alias_generators import to_camel


class NutrientSummary(BaseModel):

    energy: float = 0
    fats: float = 0
    saturated_fats: float = 0
    carbohydrates: float = 0
    sugars: float = 0
    fibre: float = 0
    protein: float = 0
    salt: float = 0

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class DailySummary(NutrientSummary):
    """
    Represents the aggregated nutritional data for a single day.
    """

    meal_count: int = 0
    snack_count: int = 0
    beverage_count: int = 0


class WeeklyBreakdown(BaseModel):
    """Holds the nutrient breakdown for a single day by meal type."""

    meals: Optional[NutrientSummary] = None
    snacks: Optional[NutrientSummary] = None
    beverages: Optional[NutrientSummary] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class SevenDayResponse(RootModel[Dict[str, Optional[WeeklyBreakdown]]]):
    """
    Represents the 7-day nutritional data response, broken down by meal type.

    The root object is a dictionary where keys are date strings (YYYY-MM-DD)
    and values contain the aggregated nutrient profiles for meals, snacks,
    and beverages for that day. A null value for a day indicates no data.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MonthlyNutritionLog(BaseModel):
    """
    Represents the aggregated nutritional data and meal logs for a single day.
    """

    meal_count: int = 0
    nutrition: NutrientSummary
    logs: List[str] = []

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MonthlySummaryResponse(RootModel[Dict[str, Optional[MonthlyNutritionLog]]]):
    """
    Represents the monthly nutrition summary response.

    The root object is a dictionary where keys are date strings (YYYY-MM-DD)
    and values contain the aggregated nutrient profiles and meal logs for that day.
    A null value for a day indicates no data.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
