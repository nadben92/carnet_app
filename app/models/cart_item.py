"""Lignes du panier utilisateur."""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CartItem(Base, TimestampMixin):
    """Article ajouté au panier (une ligne par couple vêtement / taille)."""

    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "garment_id",
            "selected_size",
            name="uq_cart_user_garment_size",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    garment_id: Mapped[int] = mapped_column(
        ForeignKey("garments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    selected_size: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="",
        server_default="",
        comment="Clé du guide des tailles (ex: S, M) ou vide si sans guide",
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
