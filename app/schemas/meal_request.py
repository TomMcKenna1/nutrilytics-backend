from typing import List, Optional
from pydantic import BaseModel, Field

from app.models.meal_response import MealResponse

class MealGenerationRequest(BaseModel):
    """Request body to generate a new meal draft."""

    description: str


class MealSaveFromDraftRequest(BaseModel):
    """
    Schema for the request body when creating a permanent meal
    from an existing draft.
    """

    draft_id: str = Field(..., alias="draftId")

class MealListResponse(BaseModel):
    """
    Defines the response structure for the latest meals endpoint.
    """
    meals: List[MealResponse] = Field(..., description="A list of the retrieved meals.")
    next: Optional[str] = Field(
        None,
        description="The document ID for the next page of results. Null if this is the last page.",
        example="aBcDeFg12345"
    )