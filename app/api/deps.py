import logging
from functools import lru_cache

from cachetools import TTLCache, cached
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

from app.db.firebase import get_firebase_auth
from app.models.user import AuthUser

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()

auth_cache = TTLCache(maxsize=1024, ttl=3600)


@lru_cache()
def get_auth_dependency() -> auth:
    """
    Cached dependency to get the Firebase auth client.
    This avoids re-initializing the auth client on every request.
    """
    return get_firebase_auth()


@cached(cache=auth_cache)
def verify_token_and_get_user_data(token: str, firebase_auth: auth) -> dict:
    """
    Verifies the Firebase ID token and returns the decoded claims.
    Results of this function are cached in the TTL cache.
    """
    try:
        logger.debug("Cache miss. Verifying token with Firebase.")
        return firebase_auth.verify_id_token(token)
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
            f"An unexpected error occurred during token verification: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during authentication.",
        )


async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    firebase_auth: auth = Depends(get_auth_dependency),
) -> AuthUser:
    """
    Validates a Firebase ID token using a local TTL cache and returns the
    corresponding User model.
    """
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    token = cred.credentials
    decoded_token = verify_token_and_get_user_data(token, firebase_auth)
    return AuthUser(
        uid=decoded_token["uid"],
        email=decoded_token.get("email"),
        name=decoded_token.get("name"),
    )
