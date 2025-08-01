# app/models/user.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from app.models.nutrition_target import NutritionTarget
from app.models.profile import UserProfileBase


class AuthUser(BaseModel):
    """Represents the authenticated user object derived from a Firebase ID token."""

    uid: str
    email: Optional[EmailStr] = None
    name: Optional[str] = None


class UserInDB(BaseModel):
    """Represents the full user document as stored in Firestore."""

    uid: str # Populated from the document ID, not a field in Firestore
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    created_at: datetime = Field(alias="createdAt")
    onboarding_complete: bool = Field(alias="onboardingComplete")
    profile: Optional[UserProfileBase] = None
    nutrition_targets: Optional[NutritionTarget] = Field(
        default=None, alias="nutritionTargets"
    )
    log_streak: int = Field(default=0, alias="logStreak")
    last_activity_at: Optional[datetime] = Field(default=None, alias="lastActivityAt")
    current_weight_kg: Optional[float] = Field(
        default=None, alias="currentWeightKg", description="The user's most recent weight."
    )

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )