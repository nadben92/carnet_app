"""Modèle User."""

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Utilisateur du Personal Shopper."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    profile: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Infos personnelles (legacy)",
    )
    measurements: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Données de mesure issues des scans utilisateurs",
    )

    user_profile: Mapped["UserProfile | None"] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
