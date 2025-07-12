import uuid
import time
from typing import Dict
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.meal import MealDraft, MealGenerationRequest
from app.services import meal_generator

router = APIRouter()

DRAFT_DB: Dict[str, MealDraft] = {}


def _generate_and_cache_meal(draft_id: str, description: str):
    """
    Worker function to run in the background.
    Simulates a long process and updates the cache.
    """
    print(f"Starting meal generation for draft: {draft_id}...")

    generated_meal = meal_generator.generate_meal(description)

    if draft_id in DRAFT_DB:
        DRAFT_DB[draft_id].status = "complete"
        DRAFT_DB[draft_id].meal = generated_meal.to_pydantic()
        print(f"Finished meal generation for draft: {draft_id}")


@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
def create_meal_draft(
    request: MealGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    """
    Creates a new meal draft. This kicks off a background task
    for the generation and immediately returns a draft ID.
    """
    draft_id = str(uuid.uuid4())

    # Store the initial pending state
    DRAFT_DB[draft_id] = MealDraft(
        status="pending", user_id=current_user.uid, meal=None
    )

    # Add the long-running generation task to the background
    background_tasks.add_task(_generate_and_cache_meal, draft_id, request.description)

    return {"draftId": draft_id}


@router.get("/{draft_id}", response_model=MealDraft)
def get_meal_draft(draft_id: str, current_user: User = Depends(get_current_user)):
    """
    Retrieves the status and data of a meal draft.
    You can poll this endpoint until the status is "complete".
    """
    draft = DRAFT_DB.get(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
        )
    if draft.user_id != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft",
        )
    return draft


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal_draft(draft_id: str, current_user: User = Depends(get_current_user)):
    """
    Discards/deletes a meal draft from the cache.
    """
    draft = DRAFT_DB.get(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
        )

    if draft.user_id != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft",
        )

    del DRAFT_DB[draft_id]
    return
