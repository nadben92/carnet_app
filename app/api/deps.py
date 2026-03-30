"""Dépendances FastAPI partagées (auth)."""

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.services.auth import decode_access_token


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> User:
    """Utilisateur connecté via Bearer JWT, ou 401."""
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
    return user
