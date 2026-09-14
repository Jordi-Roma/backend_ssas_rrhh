"""Crear tabla de parámetros legales con periodos de vigencia.

Revision ID: 20260908_0012
Revises: 20260908_0011
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0012"
down_revision: str | None = "20260908_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "parametro_legal",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "empresa_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column("vigencia_desde", sa.Date(), nullable=False),
        sa.Column("vigencia_hasta", sa.Date(), nullable=False),
        sa.Column("afp", sa.Numeric(5, 2), nullable=True),
        sa.Column("aporte_solidario", sa.Numeric(5, 2), nullable=True),
        sa.Column("rc_iva", sa.Numeric(5, 2), nullable=True),
        sa.Column("aguinaldo", sa.Numeric(5, 2), nullable=True),
        sa.Column("prima", sa.Numeric(5, 2), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["empresa_id"],
            ["empresa.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "vigencia_hasta >= vigencia_desde",
            name="chk_parametro_legal_rango_vigencia",
        ),
        sa.CheckConstraint("afp BETWEEN 0 AND 100", name="chk_parametro_legal_afp"),
        sa.CheckConstraint(
            "aporte_solidario IS NULL OR aporte_solidario BETWEEN 0 AND 100",
            name="chk_parametro_legal_aporte_solidario",
        ),
        sa.CheckConstraint(
            "rc_iva IS NULL OR rc_iva BETWEEN 0 AND 100",
            name="chk_parametro_legal_rc_iva",
        ),
        sa.CheckConstraint(
            "aguinaldo IS NULL OR aguinaldo BETWEEN 0 AND 100",
            name="chk_parametro_legal_aguinaldo",
        ),
        sa.CheckConstraint(
            "prima IS NULL OR prima BETWEEN 0 AND 100",
            name="chk_parametro_legal_prima",
        ),
    )
    op.create_index(
        "idx_parametro_legal_empresa_vigencia",
        "parametro_legal",
        ["empresa_id", "vigencia_desde"],
    )


def downgrade() -> None:
    op.drop_index("idx_parametro_legal_empresa_vigencia", table_name="parametro_legal")
    op.drop_table("parametro_legal")