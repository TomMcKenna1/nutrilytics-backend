import asyncio
from collections import defaultdict
import logging
import uuid
from typing import Any, Dict, List, Optional
from datetime import date, datetime, timedelta, timezone

from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.query import Query as FirestoreQuery
from firebase_admin import firestore

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.meal import (
    DataSource,
    MealDB,
    GeneratedMeal,
    MealComponentDB,
    MealGenerationStatus,
    NutrientProfileDB,
    ComponentType as DBComponentType,
)
from app.models.user import AuthUser, UserInDB
from app.schemas.meal_request import (
    AddComponentRequest,
    MealGenerationRequest,
    MealListResponse,
    UpdateMealTypeRequest,
)
from app.services import meal_generator
from meal_generator import (
    Meal as BusinessMeal,
    ComponentDoesNotExist,
    MealComponent,
    MealGenerationError,
    NutrientProfile,
    ComponentType as BusinessComponentType,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class Notifier:
    """Manages active SSE listeners and broadcasts messages."""

    def __init__(self):
        self.listeners: Dict[str, List[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.listeners[user_id].append(queue)
        logger.info(
            f"User '{user_id}' subscribed. Total listeners for user: {len(self.listeners[user_id])}"
        )
        return queue

    def unsubscribe(self, user_id: str, queue: asyncio.Queue):
        if user_id in self.listeners:
            self.listeners[user_id].remove(queue)
            if not self.listeners[user_id]:
                del self.listeners[user_id]
            logger.info(f"User '{user_id}' unsubscribed.")

    async def publish(self, user_id: str, message: Any):
        if user_id in self.listeners:
            logger.info(
                f"Publishing update to {len(self.listeners[user_id])} listeners for user '{user_id}'"
            )
            for queue in self.listeners[user_id]:
                await queue.put(message)


notifier = Notifier()


def _convert_db_data_to_business_logic_meal(meal_data: GeneratedMeal) -> BusinessMeal:
    """Converts a GeneratedMeal Pydantic model into a business logic Meal object."""

    def convert_nutrient_profile(np_db: NutrientProfileDB) -> NutrientProfile:
        dumped_data = np_db.model_dump()
        if "data_source" in dumped_data and isinstance(dumped_data["data_source"], str):
            dumped_data["data_source"] = DataSource(dumped_data["data_source"])
        return NutrientProfile(**dumped_data)

    components = [
        MealComponent(
            name=comp_db.name,
            quantity=comp_db.quantity,
            metric=comp_db.metric,
            total_weight=comp_db.total_weight,
            component_type=BusinessComponentType(comp_db.type.value),
            nutrient_profile=convert_nutrient_profile(comp_db.nutrient_profile),
            brand=comp_db.brand,
            source_url=comp_db.source_url,
            id=comp_db.id,
        )
        for comp_db in meal_data.components
    ]

    return BusinessMeal(
        name=meal_data.name,
        description=meal_data.description,
        meal_type=meal_data.type,
        component_list=components,
    )


def _convert_business_logic_meal_to_db_model(
    business_meal: BusinessMeal,
) -> GeneratedMeal:
    """Converts a business logic Meal into a GeneratedMeal Pydantic model for storage."""
    components_db = [
        MealComponentDB(
            id=str(comp.id),
            name=comp.name,
            brand=comp.brand,
            quantity=comp.quantity,
            total_weight=comp.total_weight,
            type=DBComponentType(comp.type.value),
            nutrient_profile=NutrientProfileDB(**comp.nutrient_profile.as_dict()),
        )
        for comp in business_meal.component_list
    ]
    return GeneratedMeal(
        name=business_meal.name,
        description=business_meal.description,
        type=business_meal.type,
        nutrient_profile=NutrientProfileDB(**business_meal.nutrient_profile.as_dict()),
        components=components_db,
    )


def _get_meal_logs_collection(db: AsyncClient, user_id: str):
    return db.collection("users").document(user_id).collection("mealLogs")


async def _generate_and_update_meal(
    db: AsyncClient, meal_id: str, description: str, user_id: str
):
    """
    Generates meal data, updates Firestore, and publishes a notification.
    """
    meal_ref = _get_meal_logs_collection(db, user_id).document(meal_id)

    try:
        business_meal = await meal_generator.generate_meal_async(description)
        generated_data_model = _convert_business_logic_meal_to_db_model(business_meal)
        update_payload = {
            "data": generated_data_model.model_dump(by_alias=True),
            "status": MealGenerationStatus.COMPLETE.value,
            "error": None,
        }
    except Exception as e:
        logger.error(f"Meal generation failed for meal '{meal_id}': {e}", exc_info=True)
        update_payload = {"status": MealGenerationStatus.ERROR.value, "error": str(e)}
    finally:
        await meal_ref.update(update_payload)
        updated_doc = await meal_ref.get()
        meal = MealDB(id=updated_doc.id, **updated_doc.to_dict())
        await notifier.publish(user_id, meal)


async def _add_component_and_update_firestore(
    db: AsyncClient, meal_id: str, description: str, user_id: str
):
    """Adds a component, updates Firestore, and publishes a notification."""
    meal_ref = _get_meal_logs_collection(db, user_id).document(meal_id)
    try:
        meal_doc = await meal_ref.get()
        if not meal_doc.exists:
            return
        meal_db = MealDB(id=meal_doc.id, **meal_doc.to_dict())
        if not meal_db.data:
            raise MealGenerationError("Cannot add component, meal data is missing.")
        business_meal = _convert_db_data_to_business_logic_meal(meal_db.data)
        await business_meal.add_component_from_string_async(
            description, meal_generator.get_meal_generator()
        )
        updated_data_model = _convert_business_logic_meal_to_db_model(business_meal)
        await meal_ref.update(
            {
                "data": updated_data_model.model_dump(by_alias=True),
                "status": MealGenerationStatus.COMPLETE.value,
                "error": None,
            }
        )
    except (MealGenerationError, Exception) as e:
        logger.error(
            f"Component generation failed for meal '{meal_id}': {e}", exc_info=True
        )
        await meal_ref.update(
            {"status": MealGenerationStatus.ERROR.value, "error": str(e)}
        )
    finally:
        updated_doc = await meal_ref.get()
        meal = MealDB(id=updated_doc.id, **updated_doc.to_dict())
        await notifier.publish(user_id, meal)


async def update_streak(db: AsyncClient, current_user: AuthUser):
    user_doc_ref = db.collection("users").document(current_user.uid)
    try:
        user_doc = await user_doc_ref.get()
        if user_doc.exists:
            user = UserInDB(uid=user_doc.id, **user_doc.to_dict())
            now = datetime.now(timezone.utc)
            today = now.date()
            new_streak = user.log_streak

            if user.last_activity_at is None:
                new_streak = 1
            else:
                last_activity_date = user.last_activity_at.date()
                if last_activity_date < today:
                    if last_activity_date == today - timedelta(days=1):
                        new_streak += 1
                    else:
                        new_streak = 1
            await user_doc_ref.update({"logStreak": new_streak, "lastActivityAt": now})
            logger.info(
                f"Updated streak for user '{current_user.uid}' to {new_streak}."
            )
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error updating streak for user '{current_user.uid}': {e}"
        )


@router.post("/", status_code=status.HTTP_202_ACCEPTED, response_model=MealDB)
async def create_meal(
    request: MealGenerationRequest,
    background_tasks: BackgroundTasks,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Creates a placeholder meal and starts the generation in the background."""
    await update_streak(db, current_user)

    doc_ref = _get_meal_logs_collection(db, current_user.uid).document()

    created_at_datetime = datetime.fromtimestamp(request.createdAt, tz=timezone.utc)

    meal_placeholder = MealDB(
        id=doc_ref.id,
        original_input=request.description,
        status=MealGenerationStatus.PENDING,
        created_at=created_at_datetime,
    )
    try:
        await doc_ref.set(
            meal_placeholder.model_dump(
                by_alias=True, exclude={"id"}, exclude_none=True
            )
        )
        background_tasks.add_task(
            _generate_and_update_meal,
            db,
            doc_ref.id,
            request.description,
            current_user.uid,
        )
        new_meal_doc = await doc_ref.get()
        return MealDB(id=new_meal_doc.id, **new_meal_doc.to_dict())
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error creating meal for user '{current_user.uid}': {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=503, detail="Database error while creating meal."
        )


@router.get("/", response_model=MealListResponse)
async def get_meal_list(
    limit: int = Query(10, ge=1, le=20),
    next_cursor: Optional[str] = Query(None, alias="next"),
    log_date: Optional[date] = Query(None, alias="date"),
    user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Retrieves a paginated list of the user's meals."""
    try:
        meals_ref = _get_meal_logs_collection(db, user.uid)

        if log_date:
            start_of_day = datetime.combine(
                log_date, datetime.min.time(), tzinfo=timezone.utc
            )
            end_of_day = datetime.combine(
                log_date, datetime.max.time(), tzinfo=timezone.utc
            )
            query = (
                meals_ref.where("createdAt", ">=", start_of_day)
                .where("createdAt", "<=", end_of_day)
                .order_by("createdAt", direction=FirestoreQuery.DESCENDING)
                .order_by("__name__", direction=FirestoreQuery.DESCENDING)
            )
        else:
            query = meals_ref.order_by(
                "createdAt", direction=FirestoreQuery.DESCENDING
            ).order_by("__name__", direction=FirestoreQuery.DESCENDING)

        if next_cursor:
            last_doc = await meals_ref.document(next_cursor).get()
            if not last_doc.exists:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid 'next' cursor.",
                )
            query = query.start_after(last_doc)
        docs = await query.limit(limit).get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore query failed for user '{user.uid}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error fetching meals.",
        )

    meals_list = [MealDB(id=doc.id, **doc.to_dict()) for doc in docs]
    next_page_cursor = docs[-1].id if len(docs) == limit else None
    return MealListResponse(meals=meals_list, next=next_page_cursor)


@router.get("/stream")
async def stream_meal_updates(
    request: Request, current_user: AuthUser = Depends(get_current_user)
):
    """
    Creates an SSE stream using FastAPI's StreamingResponse to notify the
    client of real-time updates to their meals.
    """

    async def event_generator():
        """
        Subscribes to the in-memory notifier and yields events formatted
        manually for the SSE protocol.
        """
        queue = notifier.subscribe(current_user.uid)
        try:
            while True:
                if await request.is_disconnected():
                    break

                meal_update: MealDB = await queue.get()

                event_data = meal_update.model_dump_json(by_alias=True)
                sse_message = f"event: meal_update\ndata: {event_data}\n\n"

                yield sse_message
        except asyncio.CancelledError:
            logger.info(f"SSE connection cancelled for user '{current_user.uid}'.")
        finally:
            notifier.unsubscribe(current_user.uid, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{meal_id}", response_model=MealDB)
async def get_meal_by_id(
    meal_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Retrieves a specific meal by its ID from the user's subcollection."""
    logger.info(f"User '{current_user.uid}' requesting meal '{meal_id}'.")
    try:
        doc_ref = _get_meal_logs_collection(db, current_user.uid).document(meal_id)
        meal_doc = await doc_ref.get()
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error fetching meal '{meal_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database error fetching the meal.",
        )

    if not meal_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
        )

    try:
        return MealDB(id=meal_doc.id, **meal_doc.to_dict())
    except ValidationError as e:
        logger.error(f"Meal '{meal_id}' has invalid format in DB: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not read meal data.",
        )


@router.patch("/{meal_id}/type", response_model=MealDB)
async def update_meal_type(
    meal_id: str,
    request: UpdateMealTypeRequest,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Updates the 'type' of a specific meal in the user's subcollection."""
    meal_ref = _get_meal_logs_collection(db, current_user.uid).document(meal_id)
    try:
        meal_doc = await meal_ref.get()
        if not meal_doc.exists:
            logger.warning(
                f"User '{current_user.uid}' failed to update non-existent meal '{meal_id}'."
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
            )

        meal = MealDB(id=meal_doc.id, **meal_doc.to_dict())
        if meal.status != MealGenerationStatus.COMPLETE or not meal.data:
            logger.error(
                f"Attempt to update meal '{meal_id}' in non-complete state: {meal.status}."
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Meal is not in a 'complete' state and cannot be modified.",
            )

        await meal_ref.update({"data.type": request.type.value})
        logger.info(
            f"Successfully updated meal type for '{meal_id}' for user '{current_user.uid}'."
        )
        updated_doc = await meal_ref.get()
        return MealDB(id=updated_doc.id, **updated_doc.to_dict())
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error updating meal type for '{meal_id}': {e}", exc_info=True
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while updating the meal.",
        )
    except ValidationError as e:
        logger.error(
            f"Data validation failed for meal '{meal_id}' after update: {e}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Meal data is in an invalid format.",
        )


@router.post(
    "/{meal_id}/components", status_code=status.HTTP_202_ACCEPTED, response_model=MealDB
)
async def add_component_to_meal(
    meal_id: str,
    request: AddComponentRequest,
    background_tasks: BackgroundTasks,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Adds a component to a meal's 'data', updating it in the background."""
    meal_ref = _get_meal_logs_collection(db, current_user.uid).document(meal_id)
    meal_doc = await meal_ref.get()
    if not meal_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
        )

    meal = MealDB(id=meal_doc.id, **meal_doc.to_dict())
    if meal.status != MealGenerationStatus.COMPLETE or not meal.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meal must be 'complete' with data to modify.",
        )

    await meal_ref.update({"status": MealGenerationStatus.PENDING_EDIT.value})
    background_tasks.add_task(
        _add_component_and_update_firestore,
        db,
        meal_id,
        request.description,
        current_user.uid,
    )
    meal.status = MealGenerationStatus.PENDING_EDIT
    return meal


@router.delete(
    "/{meal_id}/components/{component_id}",
    status_code=status.HTTP_200_OK,
    response_model=MealDB,
)
async def remove_component_from_meal(
    meal_id: str,
    component_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Removes a component from a meal's 'data' field synchronously."""
    meal_ref = _get_meal_logs_collection(db, current_user.uid).document(meal_id)
    try:
        meal_doc = await meal_ref.get()
        if not meal_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Meal not found"
            )

        meal = MealDB(id=meal_doc.id, **meal_doc.to_dict())
        if meal.status != MealGenerationStatus.COMPLETE or not meal.data:
            raise HTTPException(
                status_code=409,
                detail="Meal is not in a 'complete' state for modification.",
            )

        business_meal = _convert_db_data_to_business_logic_meal(meal.data)
        try:
            component_uuid = uuid.UUID(component_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid component ID.",
            )
        business_meal.remove_component(component_uuid)

        updated_data_model = _convert_business_logic_meal_to_db_model(business_meal)
        await meal_ref.update({"data": updated_data_model.model_dump(by_alias=True)})
        updated_doc = await meal_ref.get()
        return MealDB(id=updated_doc.id, **updated_doc.to_dict())
    except ComponentDoesNotExist:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Component not found in meal."
        )


@router.delete("/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meal(
    meal_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Deletes a meal from the user's subcollection."""
    logger.info(f"User '{current_user.uid}' attempting to delete meal '{meal_id}'.")
    meal_ref = _get_meal_logs_collection(db, current_user.uid).document(meal_id)
    try:
        meal_doc = await meal_ref.get()
        if not meal_doc.exists:
            logger.warning(
                f"Attempt to delete non-existent meal '{meal_id}' by user '{current_user.uid}'. "
            )
            return
        await meal_ref.delete()
        logger.info(
            f"Successfully deleted meal '{meal_id}' for user '{current_user.uid}'."
        )
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error deleting meal '{meal_id}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while deleting the meal.",
        )
