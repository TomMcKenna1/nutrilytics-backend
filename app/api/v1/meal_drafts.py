import logging
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from redis.exceptions import RedisError

from app.api.deps import get_current_user, get_redis_client
from app.models.user import User
from app.schemas.meal import MealDraft, MealGenerationRequest, MealGenerationStatus
from app.services import meal_generator
from meal_generator import MealGenerationError

logger = logging.getLogger(__name__)
router = APIRouter()


async def _generate_and_cache_meal(
    redis_client: redis.Redis, draft_id: str, description: str, user_id: str
):
    """
    Generates meal data from a description and updates the draft in Redis.

    This task runs in the background. If generation is successful, it updates
    the draft status to 'complete'. If it fails, it updates the status to 'error'.
    It includes error handling for Redis to prevent task crashes.
    """
    logger.info(f"Starting background meal generation for draft '{draft_id}'.")
    try:
        generated_meal = await meal_generator.generate_meal_async(description)
        draft_json = await redis_client.get(draft_id)

        if draft_json:
            draft = MealDraft.model_validate_json(draft_json)
            draft.status = MealGenerationStatus.COMPLETE
            draft.meal = generated_meal.to_pydantic()
            await redis_client.set(draft_id, draft.model_dump_json())
            logger.info(
                f"Successfully finished meal generation for draft '{draft_id}'."
            )
        else:
            logger.warning(
                f"Draft '{draft_id}' was deleted before generation could complete."
            )

    except MealGenerationError as e:
        logger.error(
            f"Meal generation failed for draft '{draft_id}': {e}", exc_info=True
        )
        try:
            draft_json = await redis_client.get(draft_id)
            if draft_json:
                draft = MealDraft.model_validate_json(draft_json)
                draft.status = MealGenerationStatus.ERROR
                await redis_client.set(draft_id, draft.model_dump_json())
        except RedisError as redis_err:
            logger.error(
                f"Redis error while setting draft '{draft_id}' to 'error' status: {redis_err}"
            )

    except RedisError as e:
        logger.error(
            f"Redis error during meal generation task for draft '{draft_id}': {e}"
        )


@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=dict)
async def create_meal_draft(
    request: MealGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Creates a new meal draft and starts the AI generation in the background.
    """
    draft_id = str(uuid.uuid4())
    logger.info(f"User '{current_user.uid}' creating meal draft '{draft_id}'.")

    draft = MealDraft(status=MealGenerationStatus.PENDING, uid=current_user.uid, meal=None)
    try:
        await redis_client.set(draft_id, draft.model_dump_json())
    except RedisError as e:
        logger.error(
            f"Redis error on create_meal_draft for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while creating the draft.",
        )

    background_tasks.add_task(
        _generate_and_cache_meal,
        redis_client,
        draft_id,
        request.description,
        current_user.uid,
    )

    return {"draftId": draft_id}


@router.get("/{draft_id}", response_model=MealDraft)
async def get_meal_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Retrieves the status and data of a meal draft.
    """
    logger.info(f"User '{current_user.uid}' requesting draft '{draft_id}'.")
    try:
        draft_json = await redis_client.get(draft_id)
    except RedisError as e:
        logger.error(
            f"Redis error while fetching draft '{draft_id}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while fetching the draft.",
        )

    if not draft_json:
        logger.warning(f"Draft '{draft_id}' not found for user '{current_user.uid}'.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
        )

    draft = MealDraft.model_validate_json(draft_json)
    if draft.uid != current_user.uid:
        logger.warning(
            f"User '{current_user.uid}' forbidden from accessing draft '{draft_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft",
        )
    return draft


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Deletes a meal draft from Redis after verifying ownership.
    """
    logger.info(f"User '{current_user.uid}' attempting to delete draft '{draft_id}'.")
    try:
        draft_json = await redis_client.get(draft_id)
        if not draft_json:
            logger.warning(f"Attempt to delete non-existent draft '{draft_id}'.")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
            )

        draft = MealDraft.model_validate_json(draft_json)
        if draft.uid != current_user.uid:
            logger.warning(
                f"User '{current_user.uid}' forbidden from deleting draft '{draft_id}'."
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access this draft",
            )

        await redis_client.delete(draft_id)
    except RedisError as e:
        logger.error(
            f"Redis error on delete_meal_draft for draft '{draft_id}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while deleting the draft.",
        )

    logger.info(f"Successfully deleted draft '{draft_id}'.")
    return
