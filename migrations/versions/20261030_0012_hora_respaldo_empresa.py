"""Hora local configurable para el respaldo diario por empresa.

Revision ID: 20261030_0012
Revises: 20261024_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20261030_0012"
down_revision = "20261024_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "respaldo_empresa_config",
        sa.Column("hora_local", sa.String(length=5), nullable=False, server_default="02:00"),
    )
    op.create_check_constraint(
        "ck_respaldo_empresa_config_hora_local",
        "respaldo_empresa_config",
        "hora_local ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_respaldo_empresa_config_hora_local", "respaldo_empresa_config")
    op.drop_column("respaldo_empresa_config", "hora_local")
