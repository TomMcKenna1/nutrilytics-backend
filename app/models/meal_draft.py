import enum
from typing import Optional

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models.meal import MealComponentDB, NutrientProfileDB


class MealGenerationStatus(enum.Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    ERROR = "error"

class MealDraft(BaseModel):
    name: str
    description: str
    nutrient_profile: NutrientProfileDB
    components: list[MealComponentDB]

class MealDraftDB(BaseModel):
    id: str
    uid: str
    status: MealGenerationStatus
    meal_draft: Optional[MealDraft] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
