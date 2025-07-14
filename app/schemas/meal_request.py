from pydantic import BaseModel, Field

class MealGenerationRequest(BaseModel):
    """Request body to generate a new meal draft."""

    description: str


class MealSaveFromDraftRequest(BaseModel):
    """
    Schema for the request body when creating a permanent meal
    from an existing draft.
    """

    draft_id: str = Field(..., alias="draftId")
