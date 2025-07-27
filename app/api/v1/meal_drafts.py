import logging
import uuid
from datetime import datetime, timezone
from typing import List

import redis.asyncio as redis
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from redis.exceptions import RedisError

from app.api.deps import get_current_user, get_redis_client
from app.models.user import User
from app.schemas.meal_request import MealGenerationRequest, MealSaveFromDraftRequest
from app.models.meal_draft import Draft, MealDraft, MealGenerationStatus
from app.models.meal import MealComponentDB, NutrientProfileDB

from meal_generator import MealGenerationError
from meal_generator.meal import Meal as GeneratedMeal, ComponentDoesNotExist
from meal_generator.meal_component import MealComponent
from meal_generator.nutrient_profile import NutrientProfile
from app.services import meal_generator

logger = logging.getLogger(__name__)
router = APIRouter()


class AddComponentRequest(BaseModel):
    """Request model for adding a new component to a draft."""
    description: str


def _convert_draft_to_generated_meal(draft_data: MealDraft) -> GeneratedMeal:
    """
    Converts a MealDraft Pydantic model from the cache into a business logic Meal object.
    This allows for using the business logic methods like adding or removing components.
    """

    def convert_nutrient_profile(np_db: NutrientProfileDB) -> NutrientProfile:
        return NutrientProfile(**np_db.model_dump())

    components = []
    for comp_db in draft_data.components:
        component = MealComponent(
            name=comp_db.name,
            quantity=comp_db.quantity,
            total_weight=comp_db.total_weight,
            nutrient_profile=convert_nutrient_profile(comp_db.nutrient_profile),
            brand=comp_db.brand,
        )
        # Preserve the original ID from the draft
        component.id = uuid.UUID(comp_db.id)
        components.append(component)

    meal = GeneratedMeal(
        name=draft_data.name,
        description=draft_data.description,
        meal_type=draft_data.type,
        component_list=components,
    )
    return meal


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
        type=generated_meal.type,
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
    the draft status to 'complete'. If it fails, it updates the status to 'error'
    and stores the error message.
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

        draft = Draft.model_validate_json(draft_json)
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
                draft = Draft.model_validate_json(draft_json)
                draft.status = MealGenerationStatus.ERROR
                draft.error = str(e)
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


async def _add_component_and_update_cache(
    redis_client: redis.Redis, draft_id: str, description: str
):
    """
    Generates a new component and adds it to an existing draft in the background.
    """
    logger.info(f"Starting background component addition for draft '{draft_id}'.")
    try:
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
        if not draft_json:
            logger.warning(
                f"Draft '{draft_id}' was deleted before component addition could complete."
            )
            return

        draft = Draft.model_validate_json(draft_json)
        if not draft.meal_draft:
            raise MealGenerationError(
                "Cannot add component, meal data is missing from draft."
            )

        generated_meal = _convert_draft_to_generated_meal(draft.meal_draft)
        await generated_meal.add_component_from_string_async(
            description, meal_generator.get_meal_generator()
        )

        updated_meal_draft_data = _convert_meal_to_draft_schema(generated_meal)
        draft.meal_draft = updated_meal_draft_data
        draft.status = MealGenerationStatus.COMPLETE
        draft.error = None

        await redis_client.set(
            f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
        )
        logger.info(
            f"Successfully finished component addition for draft '{draft_id}'."
        )

    except MealGenerationError as e:
        logger.error(
            f"Component generation failed for draft '{draft_id}': {e}", exc_info=True
        )
        try:
            draft_json = await redis_client.get(f"meal_draft:{draft_id}")
            if draft_json:
                draft = Draft.model_validate_json(draft_json)
                draft.status = MealGenerationStatus.ERROR
                draft.error = str(e)
                await redis_client.set(
                    f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
                )
        except RedisError as redis_err:
            logger.error(
                f"Redis error setting draft '{draft_id}' to 'error' after failed component add: {redis_err}"
            )
    except RedisError as e:
        logger.error(
            f"Redis error during component addition task for draft '{draft_id}': {e}"
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
    draft = Draft(
        id=draft_id,
        uid=current_user.uid,
        status=MealGenerationStatus.PENDING,
        original_input=request.description,
        created_at=datetime.now(timezone.utc),
    )
    try:
        pipe = redis_client.pipeline()
        pipe.set(f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True))
        pipe.zadd(
            f"user_drafts:{current_user.uid}", {draft_id: draft.created_at.timestamp()}
        )
        await pipe.execute()

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
    "/",
    response_model=List[Draft],
    response_model_by_alias=True,
)
async def get_all_meal_drafts(
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> List[Draft]:
    """
    Retrieves a list of all meal drafts for the current user, sorted by creation date.
    """
    logger.info(f"User '{current_user.uid}' requesting all their meal drafts.")
    try:
        draft_ids = await redis_client.zrevrange(
            f"user_drafts:{current_user.uid}", 0, -1
        )
        if not draft_ids:
            return []

        keys_to_fetch = [f"meal_draft:{_id}" for _id in draft_ids]
        draft_jsons = await redis_client.mget(keys_to_fetch)
        drafts = [Draft.model_validate_json(d) for d in draft_jsons if d]

        return drafts
    except RedisError as e:
        logger.error(
            f"Redis error fetching all drafts for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while fetching drafts.",
        )


@router.get(
    "/{draft_id}",
    response_model=Draft,
    response_model_by_alias=True,
)
async def get_meal_draft(
    draft_id: str,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
) -> Draft:
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

    draft = Draft.model_validate_json(draft_json)

    if draft.uid != current_user.uid:
        logger.warning(
            f"User '{current_user.uid}' forbidden from accessing draft '{draft_id}'."
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft",
        )
    return draft


@router.post(
    "/{draft_id}/components",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=Draft,
    response_model_by_alias=True,
)
async def add_component_to_draft(
    draft_id: str,
    request: AddComponentRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Accepts a request to add a new component to a meal draft. The draft status
    is immediately set to 'pending_edit', and the update happens in the background.
    """
    logger.info(
        f"User '{current_user.uid}' queuing component addition to draft '{draft_id}'."
    )
    try:
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
    except RedisError as e:
        logger.error(
            f"Redis error fetching draft '{draft_id}' for component addition: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database error."
        )

    if not draft_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
        )

    draft = Draft.model_validate_json(draft_json)

    if draft.uid != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft",
        )

    if draft.status not in [MealGenerationStatus.COMPLETE, MealGenerationStatus.ERROR]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Draft must be in a 'complete' or 'error' state for modification. Current state: {draft.status.value}",
        )

    if not draft.meal_draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal data not found in draft, cannot add component.",
        )

    draft.status = MealGenerationStatus.PENDING_EDIT
    try:
        await redis_client.set(
            f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
        )
    except RedisError as e:
        logger.error(
            f"Redis error updating draft '{draft_id}' to pending_edit: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error while updating draft status.",
        )

    background_tasks.add_task(
        _add_component_and_update_cache,
        redis_client,
        draft_id,
        request.description,
    )

    return draft


@router.delete("/{draft_id}/components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_component_from_draft(
    draft_id: str,
    component_id: str,
    current_user: User = Depends(get_current_user),
    redis_client: redis.Redis = Depends(get_redis_client),
):
    """
    Removes a component from a meal draft by its ID.
    The meal's nutrients are recalculated and the draft is updated.
    """
    logger.info(
        f"User '{current_user.uid}' attempting to remove component "
        f"'{component_id}' from draft '{draft_id}'."
    )
    try:
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
    except RedisError as e:
        logger.error(
            f"Redis error fetching draft '{draft_id}' for component removal: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database error."
        )

    if not draft_json:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
        )

    draft = Draft.model_validate_json(draft_json)

    if draft.uid != current_user.uid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this draft",
        )

    if draft.status not in [MealGenerationStatus.COMPLETE, MealGenerationStatus.ERROR]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft is not in a complete or error state for modification.",
        )

    if not draft.meal_draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal data not found in draft."
        )

    generated_meal = _convert_draft_to_generated_meal(draft.meal_draft)

    try:
        component_uuid = uuid.UUID(component_id)
        generated_meal.remove_component(component_uuid)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid component ID format."
        )
    except ComponentDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Component not found in draft."
        )

    updated_meal_draft_data = _convert_meal_to_draft_schema(generated_meal)
    draft.meal_draft = updated_meal_draft_data
    # If we are removing a component, the result is considered complete
    draft.status = MealGenerationStatus.COMPLETE
    draft.error = None

    try:
        await redis_client.set(
            f"meal_draft:{draft_id}", draft.model_dump_json(by_alias=True)
        )
    except RedisError as e:
        logger.error(
            f"Redis error on remove_component_from_draft for draft '{draft_id}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database error on update.",
        )

    logger.info(f"Successfully removed component '{component_id}' from draft '{draft_id}'.")


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
        # We must fetch the draft first to ensure the user has ownership.
        draft_json = await redis_client.get(f"meal_draft:{draft_id}")
        if not draft_json:
            # If draft doesn't exist, we can just ensure it's not in the set and return
            await redis_client.zrem(f"user_drafts:{current_user.uid}", draft_id)
            return

        draft = Draft.model_validate_json(draft_json)
        if draft.uid != current_user.uid:
            logger.warning(
                f"User '{current_user.uid}' forbidden from deleting draft '{draft_id}'."
            )
            # Do not raise 403, act as if it's not found for security.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Draft not found"
            )

        # Use a pipeline to delete the draft and remove from set atomically
        pipe = redis_client.pipeline()
        pipe.zrem(f"user_drafts:{current_user.uid}", draft_id)
        pipe.delete(f"meal_draft:{draft_id}")
        await pipe.execute()

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