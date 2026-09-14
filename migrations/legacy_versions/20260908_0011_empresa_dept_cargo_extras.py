"""Agregar campos extras a empresa, departamento y cargo.

Revision ID: 20260908_0011
Revises: 20260907_0010
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0011"
down_revision: str | None = "20260907_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Columnas extras para empresa
    op.add_column("empresa", sa.Column("descripcion", sa.Text(), nullable=True))
    op.add_column(
        "empresa",
        sa.Column(
            "color_primario",
            sa.String(length=20),
            server_default="#2563eb",
            nullable=False,
        ),
    )
    op.add_column(
        "empresa",
        sa.Column(
            "portal_publico_activo",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
    )

    # Columna codigo para departamento
    op.add_column(
        "departamento",
        sa.Column("codigo", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "uq_departamento_empresa_codigo_ci",
        "departamento",
        ["empresa_id", sa.text("lower(codigo)")],
        unique=True,
        postgresql_where=sa.text("codigo IS NOT NULL"),
    )

    # Columna codigo para cargo
    op.add_column(
        "cargo",
        sa.Column("codigo", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "uq_cargo_empresa_codigo_ci",
        "cargo",
        ["empresa_id", sa.text("lower(codigo)")],
        unique=True,
        postgresql_where=sa.text("codigo IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_cargo_empresa_codigo_ci", table_name="cargo")
    op.drop_column("cargo", "codigo")

    op.drop_index("uq_departamento_empresa_codigo_ci", table_name="departamento")
    op.drop_column("departamento", "codigo")

    op.drop_column("empresa", "portal_publico_activo")
    op.drop_column("empresa", "color_primario")
    op.drop_column("empresa", "descripcion")
