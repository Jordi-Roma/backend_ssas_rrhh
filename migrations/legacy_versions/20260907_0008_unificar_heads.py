"""Unificar las ramas historicas de Alembic.

Revision ID: 20260907_0008
Revises: 20260825_0002, 20260907_0007
Create Date: 2026-09-07
"""

from collections.abc import Sequence

revision: str = "20260907_0008"
down_revision: tuple[str, str] = ("20260825_0002", "20260907_0007")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
