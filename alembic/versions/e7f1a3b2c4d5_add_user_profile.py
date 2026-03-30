"""Add user profile column

Revision ID: e7f1a3b2c4d5
Revises: d5e9b3c2f4a6
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e7f1a3b2c4d5"
down_revision: Union[str, None] = "d5e9b3c2f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "profile",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Infos personnelles : prénom, nom, genre, taille, téléphone",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "profile")
