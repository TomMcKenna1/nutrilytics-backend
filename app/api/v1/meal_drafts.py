import logging
import uuid

import redis.asyncio as redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from redis.exceptions import RedisError

from app.api.deps import get_current_user, get_redis_client
from app.models.user import User
from app.schemas.meal_request import MealGenerationRequest, MealSaveFromDraftRequest
from app.models.meal_draft import MealDraft, MealDraftDB, MealGenerationStatus
from app.models.meal import MealComponentDB, NutrientProfileDB

from meal_generator import MealGenerationError
from meal_generator.meal import Meal as GeneratedMeal
from app.services import meal_generator

logger = logging.getLogger(__name__)
router = APIRouter()


def _convert_meal_to_draft_schema(generated_meal: GeneratedMeal) -> MealDraft:
    """
    Converts a meal object from the generation module into a MealDraft Pydantic model.
    """
    components_db = [
        MealComponentDB(
            id=str(comp.id),
            name=comp.name,
            brand=comp.brand,
            quantity=comp.quantity,
            total_weight=comp.total_weight,
            nutrient_profile=NutrientProfileDB(**comp.nutrient_profile.as_dict()),
        )
        for comp in generated_meal.component_list
    ]

    meal_draft = MealDraft(
        name=generated_meal.name,
        description=generated_meal.description,
        nutrient_profile=NutrientProfileDB(**generated_meal.nutrient_profile.as_dict()),
        components=components_db,
    )
    return meal_draft


async def _generate_and_cache_meal(
    redis_client: redis.Redis, draft_id: str, description: str
):
    """
    Generates meal data from a description and updates the draft in Redis.

    This task runs in the background. If generation is successful, it updates
    the draft status to 'complete'. If it fails, it updates the status to 'error'.
    """
    logger.info(f"Starting background meal generation for draft '{draft_id}'.")
    try:
        generated_meal_object = await meal_generator.generate_meal_async(description)
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
        if not draft_json:
            logger.warning(
                f"Draft '{draft_id}' was deleted before generation could complete."
            )
            return

        draft = MealDraftDB.model_validate_json(draft_json)
        meal_draft_data = _convert_meal_to_draft_schema(generated_meal_object)
        draft.status = MealGenerationStatus.COMPLETE
        draft.meal_draft = meal_draft_data
        await redis_client.set(
            f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
        )
        logger.info(f"Successfully finished meal generation for draft '{draft_id}'.")

    except MealGenerationError as e:
        logger.error(
            f"Meal generation failed for draft '{draft_id}': {e}", exc_info=True
        )
        try:
            draft_json = await redis_client.get(f"meal_draft:{draft_id}")
            if draft_json:
                draft = MealDraftDB.model_validate_json(draft_json)
                draft.status = MealGenerationStatus.ERROR
                await redis_client.set(
                    f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
                )
        except RedisError as redis_err:
            logger.error(
                f"Redis error while setting draft '{draft_id}' to 'error' status: {redis_err}"
            )

    except RedisError as e:
        logger.error(
            f"Redis error during meal generation task for draft '{draft_id}': {e}"
        )


@router.post(
    "/",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MealSaveFromDraftRequest,
    response_model_by_alias=True,
)
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
    draft = MealDraftDB(
        id=draft_id,
        uid=current_user.uid,
        status=MealGenerationStatus.PENDING,
        meal_draft=None,
    )
    try:
        await redis_client.set(
            f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
        )
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
    )

    return {"draftId": draft_id}


@router.get(
    "/{draft_id}",
    response_model=MealDraftDB,
    response_model_by_alias=True,
)
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
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
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
    draft = MealDraftDB.model_validate_json(draft_json)
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
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
        if not draft_json:
            return
        draft = MealDraftDB.model_validate_json(draft_json)
        if draft.uid != current_user.uid:
            logger.warning(
                f"User '{current_user.uid}' forbidden from deleting draft '{draft_id}'."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
            )

        await redis_client.delete(f"meal_draft:{draft_id}")
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
