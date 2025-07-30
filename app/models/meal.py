import enum
from typing import Optional, List, Any

from pydantic import BaseModel, ConfigDict, field_serializer
from pydantic.alias_generators import to_camel
from meal_generator import MealType


class MealGenerationStatus(str, enum.Enum):
    """Enumeration for the status of a meal's generation."""

    PENDING = "pending"
    COMPLETE = "complete"
    ERROR = "error"
    PENDING_EDIT = "pending_edit"


class ComponentType(str, enum.Enum):
    """Enumeration for the type of a meal component."""

    FOOD = "food"
    BEVERAGE = "beverage"


class NutrientProfileDB(BaseModel):
    """Defines the nutritional information for a meal or component."""

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

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MealComponentDB(BaseModel):
    """Represents a single component within a meal."""

    id: str
    name: str
    brand: Optional[str] = None
    quantity: str
    total_weight: float
    type: ComponentType
    nutrient_profile: NutrientProfileDB

    @field_serializer("type")
    def serialize_component_type(self, component_type: ComponentType, _info):
        """Converts the ComponentType enum to its string value for serialization."""
        return component_type.value

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class GeneratedMeal(BaseModel):
    """
    Represents the actual generated meal data, nested within MealDB.
    """

    name: str
    description: str
    type: MealType
    nutrient_profile: NutrientProfileDB
    components: List[MealComponentDB]

    @field_serializer("type")
    def serialize_meal_type(self, meal_type: MealType, _info):
        """Converts the MealType enum to its string value for serialization."""
        return meal_type.value

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class MealDB(BaseModel):
    """
    Represents the main meal document stored in Firestore. It contains metadata
    and the nested 'data' field for the generated meal content.
    """

    id: str
    uid: str
    original_input: str
    status: MealGenerationStatus
    created_at: Any
    error: Optional[str] = None
    data: Optional[GeneratedMeal] = None

    @field_serializer("status")
    def serialize_meal_type(self, status: MealGenerationStatus, _info):
        """Converts the MealType enum to its string value for serialization."""
        return status.value

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )
