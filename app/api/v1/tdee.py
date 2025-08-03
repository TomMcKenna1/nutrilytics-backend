import logging
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.base_query import FieldFilter

from app.api.deps import get_current_user
from app.db.firebase import get_firestore_client
from app.models.user import AuthUser
from app.models.tdee import TDEEDataPoint, TDEEValues
from app.models.tdee_history import TDEEHistory

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/",
    response_model=List[TDEEDataPoint],
    summary="Get TDEE History",
    description="Retrieves the estimated TDEE history for the user within a specified date range.",
)
async def get_tdee_history(
    start_date: date = Query(
        ..., alias="startDate", description="Start date (YYYY-MM-DD)"
    ),
    end_date: date = Query(..., alias="endDate", description="End date (YYYY-MM-DD)"),
    current_user: AuthUser = Depends(get_current_user),
    db: AsyncClient = Depends(get_firestore_client),
):
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

    history_ref = (
        db.collection("users").document(current_user.uid).collection("tdeeHistory")
    )

    start_utc = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_utc = datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)

    query = history_ref.where(filter=FieldFilter("date", ">=", start_utc)).where(
        filter=FieldFilter("date", "<=", end_utc)
    )

    docs = await query.get()

    data_map = {
        doc.to_dict()["date"].date(): TDEEHistory.model_validate(doc.to_dict())
        for doc in docs
    }

    response_data: List[TDEEDataPoint] = []
    for day_offset in range((end_date - start_date).days + 1):
        current_date = start_date + timedelta(days=day_offset)

        history_entry = data_map.get(current_date)

        if history_entry:
            response_data.append(
                TDEEDataPoint(
                    date=current_date,
                    data=TDEEValues.model_validate(
                        history_entry.model_dump(by_alias=True)
                    ),
                )
            )
        else:
            response_data.append(TDEEDataPoint(date=current_date, data=None))

    return response_data
