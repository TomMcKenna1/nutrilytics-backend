from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

class DailySummary(BaseModel):
    """
    Represents the aggregated nutritional data for a single day.
    """
    meal_count: int = 0
    snack_count: int = 0
    beverage_count: int = 0
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