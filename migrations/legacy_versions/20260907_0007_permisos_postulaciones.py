"""Agregar permisos para postulantes y tablero."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0007"
down_revision: str | None = "20260907_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISOS = [
    ("postulantes:ver", "RECLUTAMIENTO", "postulantes", "ver"),
    ("platform:postulantes:ver", "PLATFORM", "postulantes", "ver"),
    ("postulaciones:ver", "RECLUTAMIENTO", "postulaciones", "ver"),
    ("postulaciones:gestionar", "RECLUTAMIENTO", "postulaciones", "gestionar"),
    ("platform:postulaciones:ver", "PLATFORM", "postulaciones", "ver"),
    ("platform:postulaciones:gestionar", "PLATFORM", "postulaciones", "gestionar"),
]


def upgrade() -> None:
    table = sa.table(
        "permiso",
        sa.column("codigo", sa.String),
        sa.column("modulo", sa.String),
        sa.column("recurso", sa.String),
        sa.column("operacion", sa.String),
    )
    op.bulk_insert(
        table,
        [
            {"codigo": code, "modulo": module, "recurso": resource, "operacion": operation}
            for code, module, resource, operation in PERMISOS
        ],
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE ((r.empresa_id IS NULL AND p.codigo LIKE 'platform:postul%') OR "
        "(r.empresa_id IS NOT NULL AND r.codigo = 'ADMIN_EMPRESA' AND p.codigo IN "
        "('postulantes:ver', 'postulaciones:ver', 'postulaciones:gestionar'))) ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, *_ in PERMISOS)
    op.execute(f"DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo IN ({codes}))")
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codes})")