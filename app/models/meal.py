from datetime import datetime
from meal_generator.models import Meal
from pydantic import ConfigDict
from pydantic.alias_generators import to_camel

class MealResponse(Meal):
    id: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )