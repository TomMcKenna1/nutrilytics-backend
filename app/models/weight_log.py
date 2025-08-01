from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class WeightLogInDB(BaseModel):
    """Represents a weight log document as stored in and retrieved from Firestore."""

    id: str = Field(description="The unique ID of the log document.")
    date: datetime = Field(description="The UTC timestamp when the log was created.")
    weight_kg: float = Field(
        alias="weightKg", description="The weight stored in kilograms."
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
