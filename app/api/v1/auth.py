from fastapi import APIRouter, Depends
from app.api.deps import get_current_user
from app.models.user import AuthUser

router = APIRouter()


@router.get("/me", response_model=AuthUser)
def read_users_me(current_user: AuthUser = Depends(get_current_user)):
    """
    Get the current authenticated user's profile.
    """
    return current_user
