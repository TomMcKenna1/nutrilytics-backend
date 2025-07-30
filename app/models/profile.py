from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Sex(str, Enum):
    MALE = "male"
    FEMALE = "female"


class Goal(str, Enum):
    MAINTAIN_WEIGHT = "maintain_weight"
    LOSE_FAT = "lose_fat"
    GAIN_MUSCLE = "gain_muscle"


class ActivityLevel(str, Enum):
    SEDENTARY = "sedentary"
    LIGHTLY_ACTIVE = "lightly_active"
    MODERATELY_ACTIVE = "moderately_active"
    VERY_ACTIVE = "very_active"
    EXTRA_ACTIVE = "extra_active"


class UserProfileBase(BaseModel):
    """Base model for user profile data, allowing for partial updates."""

    sex: Optional[Sex] = None
    age: Optional[int] = Field(default=None, ge=13, le=120)
    height_cm: Optional[float] = Field(default=None, alias="heightCm", ge=100, le=250)
    weight_kg: Optional[float] = Field(default=None, alias="weightKg", ge=10, le=500)
    goal: Optional[Goal] = None
    activity_level: Optional[ActivityLevel] = Field(default=None, alias="activityLevel")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )


class UserProfileCreate(UserProfileBase):
    """Model used for creating a user profile, where all fields are required."""

    sex: Sex
    age: int
    height_cm: float = Field(alias="heightCm")
    weight_kg: float = Field(alias="weightKg")
    goal: Goal
    activity_level: ActivityLevel = Field(alias="activityLevel")
