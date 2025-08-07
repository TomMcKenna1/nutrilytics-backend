from typing import List, Optional
from meal_generator import MealType
from pydantic import BaseModel, Field

from app.models.meal import MealDB


class UpdateMealTypeRequest(BaseModel):
    """Schema for updating the type of a meal."""

    type: MealType


class MealGenerationRequest(BaseModel):
    """Request body to generate a new meal."""

    description: str
    createdAt: float


class AddComponentRequest(BaseModel):
    """Request model for adding a new component to a meal."""

    description: str


class MealListResponse(BaseModel):
    """Defines the response structure for the latest meals endpoint."""

    meals: List[MealDB] = Field(..., description="A list of the retrieved meals.")
    next: Optional[str] = Field(
        None,
        description="The document ID for the next page of results. Null if this is the last page.",
        example="aBcDeFg12345",
    )
