import hashlib
import logging

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
from redis.exceptions import RedisError

from app.db.firebase import get_firebase_auth
from app.models.user import User

logger = logging.getLogger(__name__)
bearer_scheme = HTTPBearer()


def get_redis_client(request: Request) -> redis.Redis:
    """
    Returns a Redis client from the shared application state.
    """
    return request.app.state.redis


async def get_current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    firebase_auth: auth = Depends(get_firebase_auth),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> User:
    """
    Validates a Firebase ID token and returns the corresponding User model.
    """
    if not cred:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    token = cred.credentials
    hashed_token = hashlib.sha256(token.encode()).hexdigest()
    cache_key = f"auth_cache:{hashed_token}"

    try:
        cached_user_json = await redis_client.get(cache_key)
        if cached_user_json:
            logger.debug("Authentication cache hit for user.")
            return User.model_validate_json(cached_user_json)
    except RedisError as e:
        logger.error(f"Redis error during auth cache lookup: {e}. Proceeding without cache.")

    logger.debug("Authentication cache miss. Verifying token with Firebase.")
    try:
        decoded_token = firebase_auth.verify_id_token(token)
        user = User(
            uid=decoded_token["uid"],
            email=decoded_token.get("email"),
            name=decoded_token.get("name"),
        )
        
        try:
            await redis_client.set(cache_key, user.model_dump_json(), ex=3600)
        except RedisError as e:
            logger.error(f"Redis error during auth cache set: {e}.")

        return user

    except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError, auth.RevokedIdTokenError) as e:
        logger.warning(f"Invalid authentication attempt: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred during authentication: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred during authentication.",
        )