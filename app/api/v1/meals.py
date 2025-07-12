from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud.firestore_v1.base_client import BaseClient
from firebase_admin import firestore

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.user import User
from app.schemas.meal import MealResponse, MealSaveFromDraftRequest
from app.api.v1.meal_drafts import DRAFT_DB

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=MealResponse)
def save_meal_from_draft(
    request: MealSaveFromDraftRequest,
    current_user: User = Depends(get_current_user),
    db: BaseClient = Depends(get_firestore_client),
):
    """
    Saves a new meal by promoting a completed meal draft from the
    cache to a permanent record in Firestore.
    """
    draft_id = request.draft_id
    draft = DRAFT_DB.get(draft_id)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found."
        )
    if draft.uid != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft.",
        )
    if draft.status != "complete" or not draft.meal:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Draft is not complete and cannot be saved.",
        )

    meal_data_to_save = draft.meal.model_dump()
    meal_data_to_save["uid"] = current_user.uid
    meal_data_to_save["createdAt"] = firestore.SERVER_TIMESTAMP
    doc_ref = db.collection("meals").document()
    doc_ref.set(meal_data_to_save)
    del DRAFT_DB[draft_id]
    new_meal_doc = doc_ref.get()
    return MealResponse(id=new_meal_doc.id, **new_meal_doc.to_dict())


@router.get("/{meal_id}", response_model=MealResponse)
def get_meal_by_id(
    meal_id: str,
    current_user: User = Depends(get_current_user),
    db: BaseClient = Depends(get_firestore_client),
):
    """
    Retrieves a specific meal by its ID.
    """
    doc_ref = db.collection("meals").document(meal_id)
    meal_doc = doc_ref.get()

    if not meal_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
        )

    meal_data = meal_doc.to_dict()

    if meal_data.get("uid") != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this meal",
        )

    return MealResponse(id=meal_doc.id, **meal_data)
