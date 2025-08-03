from datetime import datetime
from typing import List
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TDEEHistory(BaseModel):
    """
    Represents the daily TDEE estimation results and Kalman Filter state
    for a user, stored in the 'tdeeHistory' collection.
    """

    uid: str
    date: datetime
    estimated_tdee_kcal: float = Field(..., alias="estimatedTdeeKcal")
    lower_bound_kcal: float = Field(..., alias="lowerBoundKcal")
    upper_bound_kcal: float = Field(..., alias="upperBoundKcal")
    is_prediction: bool = Field(
        ...,
        alias="isPrediction",
        description="True if this day had a weight measurement, False otherwise.",
    )
    estimated_weight_kg: float = Field(..., alias="estimatedWeightKg")
    activity_multiplier: float = Field(..., alias="activityMultiplier")
    covariance_matrix: List[float] = Field(..., alias="covarianceMatrix")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
