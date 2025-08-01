from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

class WeightLogCreate(BaseModel):
    """Schema for the request body when creating a weight log."""
    weight: float = Field(gt=0, description="The user's weight.")
    unit: Literal["kg", "lbs"] = Field(description="The unit of measurement for the weight.")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )