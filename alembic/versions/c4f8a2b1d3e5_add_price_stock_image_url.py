"""Add price, stock, image_url columns

Revision ID: c4f8a2b1d3e5
Revises: 9d53added2b9
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f8a2b1d3e5"
down_revision: Union[str, None] = "9d53added2b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("garments", sa.Column("price", sa.Float(), nullable=True))
    op.add_column("garments", sa.Column("stock", sa.Integer(), nullable=True))
    op.add_column("garments", sa.Column("image_url", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("garments", "image_url")
    op.drop_column("garments", "stock")
    op.drop_column("garments", "price")
