"""API Profil utilisateur - GET /profile et PATCH /profile."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.user_profile import UserProfile

router = APIRouter(prefix="/profile", tags=["profile"])


def _measurements_complete_row(p: UserProfile | None) -> bool:
    if not p:
        return False
    return (
        p.chest_circ is not None
        and p.waist_circ is not None
        and p.hip_circ is not None
    )


class ProfileResponse(BaseModel):
    """Schéma de réponse du profil."""

    first_name: str | None = None
    height_cm: int | None = None
    weight_kg: int | None = None
    top_size: str | None = None
    bottom_size: str | None = None
    shoe_size: int | None = None
    style_preference: str | None = None
    disliked_colors: list[str] | None = None
    chest_circ: float | None = None
    waist_circ: float | None = None
    hip_circ: float | None = None
    arm_length: float | None = None
    inside_leg: float | None = None
    measurements_complete: bool = Field(
        default=False,
        description="Poitrine, taille et hanches (cm) renseignés",
    )


class ProfileUpdate(BaseModel):
    """Schéma de mise à jour du profil."""

    first_name: str | None = Field(None, max_length=100)
    height_cm: int | None = Field(None, ge=50, le=250)
    weight_kg: int | None = Field(None, ge=30, le=300)
    top_size: str | None = Field(None, max_length=20)
    bottom_size: str | None = Field(None, max_length=20)
    shoe_size: int | None = Field(None, ge=20, le=55)
    style_preference: str | None = None
    disliked_colors: list[str] | None = None
    chest_circ: float | None = Field(None, ge=50, le=200)
    waist_circ: float | None = Field(None, ge=50, le=200)
    hip_circ: float | None = Field(None, ge=50, le=200)
    arm_length: float | None = Field(None, ge=40, le=100)
    inside_leg: float | None = Field(None, ge=50, le=120)


def _profile_to_response(p: UserProfile | None) -> ProfileResponse:
    """Convertit UserProfile en ProfileResponse."""
    if not p:
        return ProfileResponse(measurements_complete=False)
    return ProfileResponse(
        first_name=p.first_name,
        height_cm=p.height_cm,
        weight_kg=p.weight_kg,
        top_size=p.top_size,
        bottom_size=p.bottom_size,
        shoe_size=p.shoe_size,
        style_preference=p.style_preference,
        disliked_colors=p.disliked_colors,
        chest_circ=p.chest_circ,
        waist_circ=p.waist_circ,
        hip_circ=p.hip_circ,
        arm_length=p.arm_length,
        inside_leg=p.inside_leg,
        measurements_complete=_measurements_complete_row(p),
    )


@router.get("", response_model=ProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileResponse:
    """
    Retourne le profil de l'utilisateur connecté.
    Header: Authorization: Bearer <token>
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()
    return _profile_to_response(profile)


@router.patch("", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfileResponse:
    """
    Met à jour le profil de l'utilisateur connecté.
    Header: Authorization: Bearer <token>
    """
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user.id)
    )
    profile = result.scalar_one_or_none()

    updates = body.model_dump(exclude_unset=True)

    if profile:
        for k, v in updates.items():
            setattr(profile, k, v)
        await db.flush()
        await db.refresh(profile)
    else:
        profile = UserProfile(user_id=user.id, **updates)
        db.add(profile)
        await db.flush()
        await db.refresh(profile)

    return _profile_to_response(profile)
