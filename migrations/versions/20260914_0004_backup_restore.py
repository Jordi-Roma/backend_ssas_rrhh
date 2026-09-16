"""agregar backup y restore administrado

Revision ID: 20260914_0004
Revises: 20260914_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_0004"
down_revision: str | None = "20260914_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISOS = (
    "platform:backup:ver",
    "platform:backup:crear",
    "platform:backup:descargar",
    "platform:backup:restaurar",
    "platform:backup:eliminar",
)


def upgrade() -> None:
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
                "modulo": "PLATFORM",
                "recurso": "backup",
                "operacion": codigo.rsplit(":", 1)[1],
                "descripcion": codigo,
            }
            for codigo in PERMISOS
        ],
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.codigo = 'SUPER_ADMIN' AND r.empresa_id IS NULL "
        "AND p.codigo LIKE 'platform:backup:%' ON CONFLICT DO NOTHING"
    )
    op.create_table(
        "respaldo",
        sa.Column("id", sa.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("nombre", sa.String(255), nullable=False),
        sa.Column("ruta_storage", sa.Text(), nullable=True),
        sa.Column("formato", sa.String(20), nullable=False),
        sa.Column("tamano_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("estado", sa.String(30), nullable=False),
        sa.Column("creado_por_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("fecha_finalizacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fecha_restauracion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restaurado_por_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("mensaje_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["creado_por_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["restaurado_por_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_respaldo_estado", "respaldo", ["estado"])
    op.create_index("idx_respaldo_fecha_creacion", "respaldo", ["fecha_creacion"])


def downgrade() -> None:
    op.drop_table("respaldo")
    op.execute(
        "DELETE FROM permiso WHERE codigo = ANY(ARRAY["
        + ",".join(f"'{codigo}'" for codigo in PERMISOS)
        + "])"
    )
