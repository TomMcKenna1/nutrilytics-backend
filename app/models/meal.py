from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class NutrientProfileDB(BaseModel):

    energy: float
    fats: float
    saturated_fats: float
    carbohydrates: float
    sugars: float
    fibre: float
    protein: float
    salt: float
    contains_dairy: bool = False
    contains_high_dairy: bool = False
    contains_gluten: bool = False
    contains_high_gluten: bool = False
    contains_histamines: bool = False
    contains_high_histamines: bool = False
    contains_sulphites: bool = False
    contains_high_sulphites: bool = False
    contains_salicylates: bool = False
    contains_high_salicylates: bool = False
    contains_capsaicin: bool = False
    contains_high_capsaicin: bool = False
    is_processed: bool = False
    is_ultra_processed: bool = False

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MealComponentDB(BaseModel):
    id: str
    name: str
    brand: Optional[str]
    quantity: str
    total_weight: float
    nutrient_profile: NutrientProfileDB

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class MealBase(BaseModel):
    name: str
    description: str
    nutrient_profile: NutrientProfileDB
    components: list[MealComponentDB]

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MealCreate(MealBase):
    pass


class MealDB(MealBase):
    id: str
    uid: str
    submitted_at: datetime
    created_at: datetime
