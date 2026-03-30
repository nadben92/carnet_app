"""Modèle UserProfile - profil détaillé lié à User (1-to-1)."""

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UserProfile(Base, TimestampMixin):
    """
    Profil utilisateur pour le Personal Shopper.
    Relation 1-to-1 avec User.
    Mesures en cm pour le conseil Fit Expert.
    """

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[int | None] = mapped_column(Integer, nullable=True)
    top_size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bottom_size: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shoe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    style_preference: Mapped[str | None] = mapped_column(Text, nullable=True)
    disliked_colors: Mapped[list[str] | None] = mapped_column(
        ARRAY(String),
        nullable=True,
        comment="Couleurs à exclure des recommandations",
    )

    # Mesures précises en cm (Fit Expert)
    chest_circ: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Tour de poitrine (cm)")
    waist_circ: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Tour de taille (cm)")
    hip_circ: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Tour de hanches (cm)")
    arm_length: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Longueur de bras (cm)")
    inside_leg: Mapped[float | None] = mapped_column(Float, nullable=True, comment="Entrejambe (cm)")

    user: Mapped["User"] = relationship("User", back_populates="user_profile")
