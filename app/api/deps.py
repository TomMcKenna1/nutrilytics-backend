# app/api/deps.py

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

from app.db.firebase import get_firebase_auth
from app.models.user import User

bearer_scheme = HTTPBearer()


def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    firebase_auth: auth = Depends(get_firebase_auth),
) -> User:
    """
    Dependency to get the current user from a Firebase ID token.
    """
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token not provided",
        )
    try:
        decoded_token = firebase_auth.verify_id_token(cred.credentials)
        return User(
            uid=decoded_token["uid"],
            email=decoded_token.get("email"),
            name=decoded_token.get("name"),
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Firebase ID token",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during authentication: {e}",
        )
