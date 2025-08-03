import logging
from datetime import datetime, timedelta, timezone, date
from typing import List
from firebase_admin import firestore

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.api_core import exceptions as google_exceptions
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.user import AuthUser
from app.models.weight_log import WeightLogInDB
from app.schemas.weight_forecast_response import WeightForecastResponse
from app.schemas.weight_log_request import WeightLogCreate

logger = logging.getLogger(__name__)
router = APIRouter()

POUNDS_TO_KG_FACTOR = 0.453592


def _get_weight_logs_collection(db: AsyncClient, user_id: str):
    return db.collection("users").document(user_id).collection("weightLogs")


def _get_weight_forecast_collection(db: AsyncClient, user_id: str):
    """Helper to get a reference to the weightForecast subcollection."""
    return db.collection("users").document(user_id).collection("weightForecast")


@router.post(
    "/",
    response_model=WeightLogInDB,
    status_code=status.HTTP_201_CREATED,
    summary="Log a new weight reading",
)
async def log_weight(
    payload: WeightLogCreate,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Creates a new weight log for the user.
    """

    weight_in_kg = payload.weight
    if payload.unit == "lbs":
        weight_in_kg = round(payload.weight * POUNDS_TO_KG_FACTOR, 2)

    log_doc_ref = _get_weight_logs_collection(db, current_user.uid).document()
    user_doc_ref = db.collection("users").document(current_user.uid)

    transaction = db.transaction()

    try:

        @firestore.async_transactional
        async def update_in_transaction(transaction):
            log_data = {
                "date": datetime.now(timezone.utc),
                "weightKg": weight_in_kg,
            }
            transaction.set(log_doc_ref, log_data)
            transaction.update(user_doc_ref, {"currentWeightKg": weight_in_kg})

        await update_in_transaction(transaction)

        created_log_doc = await log_doc_ref.get()
        return WeightLogInDB(id=created_log_doc.id, **created_log_doc.to_dict())

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error logging weight for '{current_user.uid}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while logging weight.",
        )


@router.get("/", response_model=list[WeightLogInDB], summary="Get weight log history")
async def get_weight_logs(
    start_date: date = Query(
        ...,
        alias="startDate",
        description="Start date for the query range (YYYY-MM-DD).",
    ),
    end_date: date = Query(
        ..., alias="endDate", description="End date for the query range (YYYY-MM-DD)."
    ),
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """Retrieves a list of weight logs for the user within a specified date range."""
    MAX_QUERY_DAYS = 100
    today = datetime.now(timezone.utc).date()

    if start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The start date cannot be after the end date.",
        )

    if end_date > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot query for dates in the future.",
        )

    if (end_date - start_date).days > MAX_QUERY_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"The date range cannot exceed {MAX_QUERY_DAYS} days.",
        )

    start_of_day = datetime.combine(
        start_date, datetime.min.time(), tzinfo=timezone.utc
    )
    end_of_day = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

    logs_ref = _get_weight_logs_collection(db, current_user.uid)
    query = (
        logs_ref.where(filter=FieldFilter("date", ">=", start_of_day))
        .where(filter=FieldFilter("date", "<=", end_of_day))
        .order_by("date", direction="DESCENDING")
    )

    docs = await query.get()
    return [WeightLogInDB(id=doc.id, **doc.to_dict()) for doc in docs]


@router.get(
    "/forecast",
    response_model=List[WeightForecastResponse],
    summary="Get 14-day weight forecast from today",
)
async def get_weight_forecast(
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Retrieves the 14-day weight forecast starting from today.
    """
    start_date = datetime.now(timezone.utc).date()
    end_date = start_date + timedelta(days=13)

    start_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_utc = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

    forecast_ref = _get_weight_forecast_collection(db, current_user.uid)
    query = (
        forecast_ref.where(filter=FieldFilter("date", ">=", start_utc))
        .where(filter=FieldFilter("date", "<=", end_utc))
        .order_by("date")
    )

    try:
        docs = await query.get()
        return [WeightForecastResponse(**doc.to_dict()) for doc in docs]
    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(
            f"Firestore error getting weight forecast for '{current_user.uid}': {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred while fetching the weight forecast.",
        )


@router.delete(
    "/{log_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a weight log"
)
async def delete_weight_log(
    log_id: str,
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
    """
    Deletes a specific weight log. After deletion, it recalculates and updates
    the `currentWeightKg` on the user document to maintain data consistency.
    """
    log_ref = _get_weight_logs_collection(db, current_user.uid).document(log_id)
    user_ref = db.collection("users").document(current_user.uid)

    try:
        if not (await log_ref.get()).exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Weight log not found."
            )

        await log_ref.delete()

        latest_log_query = (
            _get_weight_logs_collection(db, current_user.uid)
            .order_by("date", direction="DESCENDING")
            .limit(1)
        )
        latest_docs = await latest_log_query.get()

        new_weight = None
        if latest_docs:
            new_weight = latest_docs[0].to_dict().get("weightKg")

        await user_ref.update({"currentWeightKg": new_weight})

    except (google_exceptions.GoogleAPICallError, google_exceptions.RetryError) as e:
        logger.error(f"Firestore error deleting weight log '{log_id}': {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A database error occurred.",
        )
