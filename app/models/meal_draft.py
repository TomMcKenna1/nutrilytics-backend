import enum
from typing import Optional

from meal_generator.models import Meal
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class MealGenerationStatus(enum.Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    ERROR = "error"


class MealDraft(BaseModel):
    status: MealGenerationStatus
    uid: str
    meal: Optional[Meal] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
