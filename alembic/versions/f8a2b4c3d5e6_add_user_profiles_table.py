"""Add user_profiles table (1-to-1 with users)

Revision ID: f8a2b4c3d5e6
Revises: e7f1a3b2c4d5
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f8a2b4c3d5e6"
down_revision: Union[str, None] = "e7f1a3b2c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("height_cm", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Integer(), nullable=True),
        sa.Column("top_size", sa.String(length=20), nullable=True),
        sa.Column("bottom_size", sa.String(length=20), nullable=True),
        sa.Column("shoe_size", sa.Integer(), nullable=True),
        sa.Column("style_preference", sa.Text(), nullable=True),
        sa.Column(
            "disliked_colors",
            postgresql.ARRAY(sa.String()),
            nullable=True,
            comment="Couleurs à exclure des recommandations",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_profiles_user_id"),
        "user_profiles",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_user_profiles_user_id"), table_name="user_profiles")
    op.drop_table("user_profiles")
