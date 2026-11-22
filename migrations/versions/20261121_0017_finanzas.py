"""Libro financiero global para suscripciones y gastos.

Revision ID: 20261121_0017
Revises: 20261121_0016
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20261121_0017"
down_revision = "20261121_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "movimiento_financiero",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("empresa_id", UUID(as_uuid=False), sa.ForeignKey("empresa.id", ondelete="SET NULL")),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("categoria", sa.String(120), nullable=False),
        sa.Column("monto", sa.Numeric(14, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("fuente", sa.String(30), nullable=False),
        sa.Column("referencia", sa.String(160), nullable=False, unique=True),
        sa.Column("descripcion", sa.Text()),
        sa.Column("entorno_prueba", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_movimiento_financiero_fecha", "movimiento_financiero", ["fecha", "moneda", "entorno_prueba"])


def downgrade():
    op.drop_index("ix_movimiento_financiero_fecha", table_name="movimiento_financiero")
    op.drop_table("movimiento_financiero")
