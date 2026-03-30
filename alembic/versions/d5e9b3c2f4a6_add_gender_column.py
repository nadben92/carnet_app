"""Add gender column

Revision ID: d5e9b3c2f4a6
Revises: c4f8a2b1d3e5
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e9b3c2f4a6"
down_revision: Union[str, None] = "c4f8a2b1d3e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "garments",
        sa.Column("gender", sa.String(20), nullable=True, comment="homme, femme, unisex"),
    )
    op.create_index("ix_garments_gender", "garments", ["gender"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_garments_gender", table_name="garments")
    op.drop_column("garments", "gender")
