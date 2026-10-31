"""Funciones contratables por plan.

Revision ID: 20261030_0013
Revises: 20261030_0012
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261030_0013"
down_revision = "20261030_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "plan_suscripcion",
        sa.Column("funciones", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (ORDER BY precio_mensual, id) AS position,
                   count(*) OVER () AS total
            FROM plan_suscripcion
        )
        UPDATE plan_suscripcion AS plan
        SET funciones = CASE
            WHEN ranked.position = ranked.total AND ranked.total > 1
                THEN '["importacion_masiva", "reportes_avanzados", "analisis_cv_ia", "reportes_ia_voz", "horario_respaldo"]'::jsonb
            WHEN ranked.position > 1
                THEN '["importacion_masiva", "reportes_avanzados", "analisis_cv_ia"]'::jsonb
            ELSE '[]'::jsonb
        END
        FROM ranked WHERE ranked.id = plan.id
    """)


def downgrade() -> None:
    op.drop_column("plan_suscripcion", "funciones")
