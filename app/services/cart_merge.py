"""Fusion d’articles dans le panier — logique partagée API + agent."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cart_item import CartItem
from app.models.garment import Garment


class CartMergeError(Exception):
    """Erreur métier panier (code HTTP + message)."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def normalize_cart_size(raw: str | None) -> str:
    return (raw or "").strip()


def validated_size_for_garment(garment: Garment, size: str) -> str:
    """Retourne la taille validée ou lève CartMergeError."""
    guide = garment.size_guide
    if not guide or not isinstance(guide, dict) or len(guide) == 0:
        if size:
            raise CartMergeError(
                400,
                "Cet article n'a pas de guide des tailles : ne pas envoyer de taille.",
            )
        return ""
    if not size:
        raise CartMergeError(400, "Choisissez une taille pour cet article.")
    if size not in guide:
        raise CartMergeError(400, "Taille non proposée pour cet article.")
    return size


def clamp_qty_to_stock(qty: int, stock: int | None) -> int:
    if stock is None:
        return qty
    return min(qty, max(0, stock))


async def merge_line_into_cart(
    db: AsyncSession,
    user_id: int,
    garment_id: int,
    size_raw: str | None,
    quantity: int = 1,
) -> None:
    """
    Ajoute ou fusionne une ligne panier pour (user, vêtement, taille).
    Lève CartMergeError en cas d’erreur métier.
    """
    g_result = await db.execute(select(Garment).where(Garment.id == garment_id))
    garment = g_result.scalar_one_or_none()
    if not garment:
        raise CartMergeError(404, "Article introuvable")

    if garment.stock is not None and garment.stock <= 0:
        raise CartMergeError(400, "Article en rupture de stock")

    size = validated_size_for_garment(garment, normalize_cart_size(size_raw))

    desired = clamp_qty_to_stock(quantity, garment.stock)
    if desired < 1:
        raise CartMergeError(400, "Stock insuffisant")

    c_result = await db.execute(
        select(CartItem).where(
            CartItem.user_id == user_id,
            CartItem.garment_id == garment_id,
            CartItem.selected_size == size,
        )
    )
    existing = c_result.scalar_one_or_none()

    if existing:
        new_qty = existing.quantity + quantity
        new_qty = clamp_qty_to_stock(new_qty, garment.stock)
        if new_qty < 1:
            raise CartMergeError(400, "Stock insuffisant")
        existing.quantity = new_qty
        await db.flush()
    else:
        db.add(
            CartItem(
                user_id=user_id,
                garment_id=garment_id,
                selected_size=size,
                quantity=desired,
            )
        )
        await db.flush()
