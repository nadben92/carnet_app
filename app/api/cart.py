"""API panier — articles par utilisateur connecté."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.cart_item import CartItem
from app.models.garment import Garment
from app.models.user import User
from app.services.cart_merge import CartMergeError, clamp_qty_to_stock, merge_line_into_cart

router = APIRouter(prefix="/cart", tags=["cart"])


class CartLineOut(BaseModel):
    """Une ligne du panier avec infos article."""

    line_id: int
    garment_id: int
    size: str = Field(
        "",
        description="Taille (clé du guide), vide si l'article n'a pas de guide",
    )
    quantity: int
    name: str
    brand: str
    category: str
    price: float | None
    image_url: str | None
    stock: int | None


class CartOut(BaseModel):
    """Panier complet."""

    items: list[CartLineOut]
    item_count: int
    subtotal: float


class AddCartItemBody(BaseModel):
    """Ajout au panier."""

    garment_id: int = Field(..., ge=1)
    quantity: int = Field(1, ge=1, le=99)
    size: str | None = Field(
        None,
        max_length=50,
        description="Taille : une clé du guide (ex. S, M, 42). Omis ou vide si pas de guide.",
    )


class UpdateCartItemBody(BaseModel):
    """Mise à jour de la quantité."""

    quantity: int = Field(..., ge=1, le=99)


def _line_from_row(ci: CartItem, garment: Garment) -> CartLineOut:
    return CartLineOut(
        line_id=ci.id,
        garment_id=garment.id,
        size=ci.selected_size,
        quantity=ci.quantity,
        name=garment.name,
        brand=garment.brand,
        category=garment.category,
        price=garment.price,
        image_url=garment.image_url,
        stock=garment.stock,
    )


def _subtotal(lines: list[CartLineOut]) -> float:
    total = 0.0
    for line in lines:
        if line.price is not None:
            total += line.price * line.quantity
    return round(total, 2)


@router.get("", response_model=CartOut)
async def get_cart(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CartOut:
    """Liste le panier de l'utilisateur connecté."""
    result = await db.execute(
        select(CartItem, Garment)
        .join(Garment, Garment.id == CartItem.garment_id)
        .where(CartItem.user_id == user.id)
        .order_by(CartItem.created_at)
    )
    rows = result.all()
    items = [_line_from_row(ci, g) for ci, g in rows]
    item_count = sum(line.quantity for line in items)
    return CartOut(items=items, item_count=item_count, subtotal=_subtotal(items))


@router.post("/items", response_model=CartOut)
async def add_cart_item(
    body: AddCartItemBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CartOut:
    """Ajoute un article au panier (ou augmente la quantité si même taille)."""
    try:
        await merge_line_into_cart(
            db,
            user.id,
            body.garment_id,
            body.size,
            body.quantity,
        )
    except CartMergeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    return await get_cart(db, user)


@router.patch("/items/{line_id}", response_model=CartOut)
async def update_cart_item(
    line_id: int,
    body: UpdateCartItemBody,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CartOut:
    """Met à jour la quantité d'une ligne du panier."""
    c_result = await db.execute(
        select(CartItem, Garment)
        .join(Garment, Garment.id == CartItem.garment_id)
        .where(
            CartItem.id == line_id,
            CartItem.user_id == user.id,
        )
    )
    row = c_result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Ligne absente du panier")
    line, garment = row

    qty = clamp_qty_to_stock(body.quantity, garment.stock)
    if qty < 1:
        raise HTTPException(status_code=400, detail="Stock insuffisant")

    line.quantity = qty
    await db.flush()
    return await get_cart(db, user)


@router.delete("/items/{line_id}", response_model=CartOut)
async def remove_cart_item(
    line_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CartOut:
    """Retire une ligne du panier."""
    await db.execute(
        delete(CartItem).where(
            CartItem.id == line_id,
            CartItem.user_id == user.id,
        )
    )
    await db.flush()
    return await get_cart(db, user)
