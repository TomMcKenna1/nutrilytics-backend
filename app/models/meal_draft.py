import enum
from typing import Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer
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

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class Draft(BaseModel):
    """
    Represents a meal draft stored in Redis. This model is also used for API responses.
    """
    id: str
    uid: str
    original_input: str
    status: MealGenerationStatus
    created_at: datetime
    meal_draft: Optional[MealDraft] = None
    error: Optional[str] = None

    @field_serializer('created_at')
    def serialize_created_at(self, value: datetime, _info):
        """Converts the created_at datetime to a Unix timestamp."""
        return value.timestamp()

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )