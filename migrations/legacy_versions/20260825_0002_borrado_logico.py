"""Agrega eliminación lógica recuperable a empresas y usuarios.

Revision ID: 20260825_0002
Revises: 20260825_0001
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISOS = (
    (
        "usuarios:eliminar",
        "USUARIOS",
        "usuarios",
        "eliminar",
        "Eliminar lógicamente usuarios del alcance autorizado",
    ),
    (
        "usuarios:restaurar",
        "USUARIOS",
        "usuarios",
        "restaurar",
        "Restaurar usuarios eliminados del alcance autorizado",
    ),
    (
        "platform:empresas:eliminar",
        "PLATFORM",
        "empresas",
        "eliminar",
        "Eliminar lógicamente empresas de la plataforma",
    ),
    (
        "platform:empresas:restaurar",
        "PLATFORM",
        "empresas",
        "restaurar",
        "Restaurar empresas eliminadas de la plataforma",
    ),
)


def upgrade() -> None:
    op.add_column("empresa", sa.Column("eliminado_at", sa.DateTime(timezone=True)))
    op.add_column("empresa", sa.Column("eliminado_por_id", sa.UUID(as_uuid=False)))
    op.create_index("idx_empresa_eliminado_at", "empresa", ["eliminado_at"])

    op.add_column("usuario", sa.Column("eliminado_at", sa.DateTime(timezone=True)))
    op.add_column("usuario", sa.Column("eliminado_por_id", sa.UUID(as_uuid=False)))
    op.create_index("idx_usuario_eliminado_at", "usuario", ["eliminado_at"])

    permiso = sa.table(
        "permiso",
        sa.column("codigo", sa.String),
        sa.column("modulo", sa.String),
        sa.column("recurso", sa.String),
        sa.column("operacion", sa.String),
        sa.column("descripcion", sa.String),
    )
    op.bulk_insert(
        permiso,
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
        "AND p.codigo IN ('platform:empresas:eliminar', 'platform:empresas:restaurar') "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.empresa_id IS NOT NULL AND r.codigo = 'ADMIN_EMPRESA' "
        "AND p.codigo IN ('usuarios:eliminar', 'usuarios:restaurar') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    codigos = ", ".join(f"'{item[0]}'" for item in PERMISOS)
    op.execute(f"DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo IN ({codigos}))")
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codigos})")

    op.drop_index("idx_usuario_eliminado_at", table_name="usuario")
    op.drop_column("usuario", "eliminado_por_id")
    op.drop_column("usuario", "eliminado_at")
    op.drop_index("idx_empresa_eliminado_at", table_name="empresa")
    op.drop_column("empresa", "eliminado_por_id")
    op.drop_column("empresa", "eliminado_at")
