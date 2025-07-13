import logging

import redis.asyncio as redis
from cachetools import TTLCache
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

from app.db.firebase import get_firebase_auth
from app.models.user import User

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()

# Token cache
auth_cache = TTLCache(maxsize=1024, ttl=3600)


def get_redis_client(request: Request) -> redis.Redis:
    """
    Returns a Redis client from the shared application state.
    """
    return request.app.state.redis


def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    firebase_auth: auth = Depends(get_firebase_auth),
) -> User:
    """
    Validates a Firebase ID token and returns the corresponding User model.

    Raises:
        HTTPException(401): If the token is invalid, expired, revoked, or not provided.
        HTTPException(500): For any other unexpected errors during authentication.

    Returns:
        The authenticated User object.
    """
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )
    if cred.credentials in auth_cache:
        return auth_cache[cred.credentials]

    try:
        decoded_token = firebase_auth.verify_id_token(cred.credentials)
        user = User(
            uid=decoded_token["uid"],
            email=decoded_token.get("email"),
            name=decoded_token.get("name"),
        )
        auth_cache[cred.credentials] = user
        return user

    except (
        auth.InvalidIdTokenError,
        auth.ExpiredIdTokenError,
        auth.RevokedIdTokenError,
    ) as e:
        logger.warning(f"Invalid authentication attempt: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
        )
    except Exception as e:
        logger.error(
            f"An unexpected error occurred during authentication: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during authentication.",
        )
