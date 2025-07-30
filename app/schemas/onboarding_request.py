from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.models.nutrition_target import NutritionTarget
from app.models.profile import UserProfileCreate


class OnboardingRequest(BaseModel):
    """
    Defines the complete payload required to onboard a user.
    This includes all mandatory profile fields and the initial nutrition targets.
    """

    profile: UserProfileCreate
    nutrition_targets: NutritionTarget = Field(alias="nutritionTargets")

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )
