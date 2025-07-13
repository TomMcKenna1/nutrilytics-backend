from datetime import datetime
import enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from meal_generator.models import Meal

class MealGenerationStatus(enum.Enum):
    PENDING = "pending"
    COMPLETE = "complete"
    ERROR = "error"

class MealGenerationRequest(BaseModel):
    """Request body to generate a new meal draft."""

    description: str


class MealDraft(BaseModel):
    """Schema for the draft stored in our cache and returned to the user."""

    status: MealGenerationStatus
    uid: str
    meal: Optional[Meal] = None

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MealSaveFromDraftRequest(BaseModel):
    """
    Schema for the request body when creating a permanent meal
    from an existing draft.
    """

    draft_id: str = Field(..., alias="draftId")


class MealResponse(Meal):
    """
    Schema for returning a meal from the database, including the
    database ID and creation timestamp.
    """

    id: str
    created_at: datetime

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
