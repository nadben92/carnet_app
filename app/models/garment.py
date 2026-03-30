"""Modèle Garment avec support Vectoriel."""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Garment(Base, TimestampMixin):
    """Vêtement du catalogue avec capacité de recherche par IA."""

    __tablename__ = "garments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    gender: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True, comment="homme, femme, unisex"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Structure: {"S": {"chest": [88, 92], "waist": [76, 80], "hip": [92, 96]}, "M": {...}}
    size_guide: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Guide des tailles: clés=S/M/L ou 38/40..., valeurs=plages [min,max] en cm (chest, waist, hip)",
    )
    # Support vectoriel pour Mistral AI
    # On utilise 1024 dimensions, ce qui correspond au modèle 'mistral-embed'
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024), 
        nullable=True,
        comment="Signature sémantique du vêtement (générée par Mistral AI)"
    )