"""Add selected_size to cart_items, unique per user+garment+size

Revision ID: i9j0k1l2m3n4
Revises: h7i8j9k0l1m2
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h7i8j9k0l1m2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_cart_user_garment", "cart_items", type_="unique")
    op.add_column(
        "cart_items",
        sa.Column(
            "selected_size",
            sa.String(length=50),
            server_default="",
            nullable=False,
            comment="Clé du guide des tailles (ex: S, M) ou vide si sans guide",
        ),
    )
    op.create_unique_constraint(
        "uq_cart_user_garment_size",
        "cart_items",
        ["user_id", "garment_id", "selected_size"],
    )
    op.alter_column("cart_items", "selected_size", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_cart_user_garment_size", "cart_items", type_="unique")
    op.drop_column("cart_items", "selected_size")
    op.create_unique_constraint(
        "uq_cart_user_garment",
        "cart_items",
        ["user_id", "garment_id"],
    )
