"""Agregar permisos para gestion de vacantes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0005"
down_revision: str | None = "20260906_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISOS = [
    ("vacantes:ver", "RECLUTAMIENTO", "vacantes", "ver", "Consultar vacantes de la empresa"),
    ("vacantes:crear", "RECLUTAMIENTO", "vacantes", "crear", "Crear vacantes de la empresa"),
    ("vacantes:editar", "RECLUTAMIENTO", "vacantes", "editar", "Editar vacantes en borrador"),
    ("vacantes:publicar", "RECLUTAMIENTO", "vacantes", "publicar", "Publicar vacantes"),
    ("vacantes:eliminar", "RECLUTAMIENTO", "vacantes", "eliminar", "Eliminar vacantes"),
    (
        "platform:vacantes:gestionar",
        "PLATFORM",
        "vacantes",
        "gestionar",
        "Gestionar vacantes de cualquier empresa",
    ),
]


def upgrade() -> None:
    permiso_table = sa.table(
        "permiso",
        sa.column("codigo", sa.String),
        sa.column("modulo", sa.String),
        sa.column("recurso", sa.String),
        sa.column("operacion", sa.String),
        sa.column("descripcion", sa.String),
    )
    op.bulk_insert(
        permiso_table,
        [
            {
                "codigo": codigo,
                "modulo": modulo,
                "recurso": recurso,
                "operacion": operacion,
                "descripcion": descripcion,
            }
            for codigo, modulo, recurso, operacion, descripcion in PERMISOS
        ],
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.empresa_id IS NULL AND r.codigo = 'SUPER_ADMIN' "
        "AND p.codigo = 'platform:vacantes:gestionar' ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.empresa_id IS NOT NULL AND r.codigo = 'ADMIN_EMPRESA' "
        "AND p.codigo IN ('vacantes:ver', 'vacantes:crear', 'vacantes:editar', "
        "'vacantes:publicar', 'vacantes:eliminar') ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{codigo}'" for codigo, *_ in PERMISOS)
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        f"(SELECT id FROM permiso WHERE codigo IN ({codes}))"
    )
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codes})")
