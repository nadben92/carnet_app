"""API d'authentification : inscription et connexion."""

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    """Corps de la requête d'inscription."""

    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., min_length=8, description="Mot de passe (min 8 caractères)")


class LoginRequest(BaseModel):
    """Corps de la requête de connexion."""

    email: EmailStr = Field(..., description="Email de l'utilisateur")
    password: str = Field(..., description="Mot de passe")


class AuthResponse(BaseModel):
    """Réponse commune register/login."""

    access_token: str = Field(..., description="Token JWT")
    token_type: str = Field(default="bearer", description="Type du token")
    user: dict = Field(..., description="Infos utilisateur (email)")


class UserResponse(BaseModel):
    """Réponse pour l'utilisateur connecté."""

    email: str
    id: int
    profile: dict | None = None


class ProfileUpdate(BaseModel):
    """Mise à jour des infos personnelles."""

    first_name: str | None = Field(None, max_length=100)
    last_name: str | None = Field(None, max_length=100)
    gender: str | None = Field(None, max_length=20)  # homme, femme, unisex
    size: str | None = Field(None, max_length=20)
    phone: str | None = Field(None, max_length=20)


@router.post("/register", response_model=AuthResponse)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Création d'un compte utilisateur.
    Retourne un token JWT si l'inscription réussit.
    """
    # Vérifier si l'email existe déjà
    result = await db.execute(select(User).where(User.email == body.email))
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    token = create_access_token(subject=body.email)
    return AuthResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "profile": user.profile},
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """
    Connexion d'un utilisateur.
    Retourne un token JWT si les identifiants sont valides.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token = create_access_token(subject=user.email)
    return AuthResponse(
        access_token=token,
        user={"id": user.id, "email": user.email, "profile": user.profile},
    )


@router.get("/me", response_model=UserResponse)
async def me(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserResponse:
    """
    Retourne l'utilisateur connecté si le token est valide.
    Header: Authorization: Bearer <token>
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token manquant ou invalide")
    token = authorization[7:].strip()
    email = decode_access_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Token expiré ou invalide")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return UserResponse(email=user.email, id=user.id, profile=user.profile)


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> UserResponse:
    """
    Met à jour les infos personnelles de l'utilisateur connecté.
    Header: Authorization: Bearer <token>
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token manquant ou invalide")
    token = authorization[7:].strip()
    email = decode_access_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="Token expiré ou invalide")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    # Mise à jour du profil (fusion avec les valeurs existantes)
    updates = body.model_dump(exclude_unset=True)
    if updates:
        current = user.profile or {}
        user.profile = {**current, **updates}
        await db.flush()
        await db.refresh(user)

    return UserResponse(email=user.email, id=user.id, profile=user.profile)

