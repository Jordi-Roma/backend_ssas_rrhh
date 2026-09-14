"""agregar codigo seguimiento postulacion

Revision ID: 20260906_0004
Revises: 20260906_0003
Create Date: 2026-09-06 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0004"
down_revision: str | None = "20260906_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "postulacion",
        sa.Column("codigo_seguimiento", sa.String(length=40), nullable=True),
    )
    op.execute(
        """
        UPDATE postulacion
        SET codigo_seguimiento = 'POST-' || upper(substr(replace(id::text, '-', ''), 1, 8))
        WHERE codigo_seguimiento IS NULL
        """
    )
    op.alter_column("postulacion", "codigo_seguimiento", nullable=False)
    op.create_unique_constraint(
        "uq_postulacion_codigo_seguimiento",
        "postulacion",
        ["codigo_seguimiento"],
    )
    op.create_index(
        "idx_postulacion_codigo_seguimiento",
        "postulacion",
        ["codigo_seguimiento"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_postulacion_codigo_seguimiento", table_name="postulacion")
    op.drop_constraint("uq_postulacion_codigo_seguimiento", "postulacion", type_="unique")
    op.drop_column("postulacion", "codigo_seguimiento")
