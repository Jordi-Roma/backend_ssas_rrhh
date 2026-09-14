"""Agregar permisos para gestionar habilidades."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0006"
down_revision: str | None = "20260907_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISOS = [
    ("habilidades:ver", "RECLUTAMIENTO", "habilidades", "ver"),
    ("habilidades:gestionar", "RECLUTAMIENTO", "habilidades", "gestionar"),
    ("platform:habilidades:gestionar", "PLATFORM", "habilidades", "gestionar"),
]


def upgrade() -> None:
    permiso_table = sa.table(
        "permiso",
        sa.column("codigo", sa.String),
        sa.column("modulo", sa.String),
        sa.column("recurso", sa.String),
        sa.column("operacion", sa.String),
    )
    op.bulk_insert(
        permiso_table,
        [
            {
                "codigo": code,
                "modulo": module,
                "recurso": resource,
                "operacion": operation,
            }
            for code, module, resource, operation in PERMISOS
        ],
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE ((r.empresa_id IS NULL AND p.codigo = 'platform:habilidades:gestionar') "
        "OR (r.empresa_id IS NOT NULL AND r.codigo = 'ADMIN_EMPRESA' "
        "AND p.codigo IN ('habilidades:ver', 'habilidades:gestionar'))) "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{code}'" for code, *_ in PERMISOS)
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        f"(SELECT id FROM permiso WHERE codigo IN ({codes}))"
    )
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codes})")