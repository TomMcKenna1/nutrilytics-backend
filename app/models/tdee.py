from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TDEEValues(BaseModel):
    """Represents the core TDEE data for a single day."""

    estimated_tdee_kcal: float = Field(alias="estimatedTdeeKcal")
    estimated_weight_kg: float = Field(alias="estimatedWeightKg")
    lower_bound_kcal: float = Field(alias="lowerBoundKcal")
    upper_bound_kcal: float = Field(alias="upperBoundKcal")

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class TDEEDataPoint(BaseModel):
    """Represents a single point in a time series, which may or may not have data."""

    date: date
    data: Optional[TDEEValues] = Field(
        default=None,
        description="Nutritional data for this date. Null if no data was logged.",
    )

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
