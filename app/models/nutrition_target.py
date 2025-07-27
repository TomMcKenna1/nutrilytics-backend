from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class NutritionTarget(BaseModel):
    """
    Pydantic model for validating and managing user-defined daily nutrition targets.
    All fields are optional to allow for partial updates.
    """

    energy: Optional[float] = Field(
        default=None, gt=0, description="Daily energy target in kcal."
    )
    fats: Optional[float] = Field(
        default=None, gt=0, description="Daily total fats target in grams."
    )
    saturated_fats: Optional[float] = Field(
        default=None, gt=0, description="Daily saturated fats target in grams."
    )
    carbohydrates: Optional[float] = Field(
        default=None, gt=0, description="Daily carbohydrates target in grams."
    )
    sugars: Optional[float] = Field(
        default=None, gt=0, description="Daily sugars target in grams."
    )
    fibre: Optional[float] = Field(
        default=None, gt=0, description="Daily fibre target in grams."
    )
    protein: Optional[float] = Field(
        default=None, gt=0, description="Daily protein target in grams."
    )
    salt: Optional[float] = Field(
        default=None, gt=0, description="Daily salt target in grams."
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )
