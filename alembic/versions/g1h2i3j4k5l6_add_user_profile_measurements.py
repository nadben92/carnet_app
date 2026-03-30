"""Add user profile measurements (Fit Expert)

Revision ID: g1h2i3j4k5l6
Revises: f8a2b4c3d5e6
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1h2i3j4k5l6"
down_revision: Union[str, None] = "f8a2b4c3d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("chest_circ", sa.Float(), nullable=True, comment="Tour de poitrine (cm)"),
    )
    op.add_column(
        "user_profiles",
        sa.Column("waist_circ", sa.Float(), nullable=True, comment="Tour de taille (cm)"),
    )
    op.add_column(
        "user_profiles",
        sa.Column("hip_circ", sa.Float(), nullable=True, comment="Tour de hanches (cm)"),
    )
    op.add_column(
        "user_profiles",
        sa.Column("arm_length", sa.Float(), nullable=True, comment="Longueur de bras (cm)"),
    )
    op.add_column(
        "user_profiles",
        sa.Column("inside_leg", sa.Float(), nullable=True, comment="Entrejambe (cm)"),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "inside_leg")
    op.drop_column("user_profiles", "arm_length")
    op.drop_column("user_profiles", "hip_circ")
    op.drop_column("user_profiles", "waist_circ")
    op.drop_column("user_profiles", "chest_circ")
