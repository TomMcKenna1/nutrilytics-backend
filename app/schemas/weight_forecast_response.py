from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class WeightForecastResponse(BaseModel):
    """Defines the shape of a single day's weight forecast."""

    date: datetime
    predicted_weight_kg: float = Field(..., alias="predictedWeightKg")
    lower_bound_kg: float = Field(..., alias="lowerBoundKg")
    upper_bound_kg: float = Field(..., alias="upperBoundKg")
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        json_encoders={datetime: lambda dt: dt.isoformat()},
    )
