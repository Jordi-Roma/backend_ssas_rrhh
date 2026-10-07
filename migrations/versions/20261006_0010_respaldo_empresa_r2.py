"""Respaldos independientes por empresa.

Revision ID: 20261006_0010
Revises: 20261005_0009
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20261006_0010"
down_revision = "20261005_0009"
branch_labels = None
depends_on = None

PERMISOS = ("backup:ver", "backup:crear", "backup:descargar")


def upgrade() -> None:
    op.create_table(
        "respaldo_empresa",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("empresa_id", UUID(as_uuid=False), sa.ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("origen", sa.String(10), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("creado_por_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")),
        sa.Column("fecha_creacion", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True)),
        sa.Column("fecha_finalizacion", sa.DateTime(timezone=True)),
        sa.Column("intentos", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ruta_storage", sa.Text()),
        sa.Column("tamano_bytes", sa.BigInteger()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("version_formato", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mensaje_error", sa.Text()),
    )
    op.create_index("idx_respaldo_empresa_fecha", "respaldo_empresa", ["empresa_id", "fecha_creacion"])
    op.create_index("idx_respaldo_empresa_estado", "respaldo_empresa", ["estado"])
    op.execute(
        "CREATE UNIQUE INDEX uq_respaldo_empresa_activo ON respaldo_empresa (empresa_id) "
        "WHERE estado IN ('PENDIENTE', 'PROCESANDO')"
    )
    op.create_table(
        "respaldo_empresa_config",
        sa.Column("empresa_id", UUID(as_uuid=False), sa.ForeignKey("empresa.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("auto_habilitado", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    permiso = sa.table(
        "permiso",
        sa.column("codigo", sa.String()), sa.column("modulo", sa.String()),
        sa.column("recurso", sa.String()), sa.column("operacion", sa.String()),
        sa.column("descripcion", sa.String()),
    )
    op.bulk_insert(permiso, [
        {"codigo": code, "modulo": "BACKUP", "recurso": "backup", "operacion": code.rsplit(":", 1)[1], "descripcion": code}
        for code in PERMISOS
    ])
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.codigo = 'ADMIN_EMPRESA' AND r.empresa_id IS NOT NULL "
        "AND p.codigo IN ('backup:ver','backup:crear','backup:descargar') "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) "
        "VALUES ('platform:backup:configurar', 'PLATFORM', 'backup', 'configurar', "
        "'Configurar respaldos automáticos por empresa')"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.codigo = 'SUPER_ADMIN' AND r.empresa_id IS NULL "
        "AND p.codigo = 'platform:backup:configurar' ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    op.drop_table("respaldo_empresa_config")
    op.execute("DROP INDEX uq_respaldo_empresa_activo")
    op.drop_index("idx_respaldo_empresa_estado", table_name="respaldo_empresa")
    op.drop_index("idx_respaldo_empresa_fecha", table_name="respaldo_empresa")
    op.drop_table("respaldo_empresa")
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        "(SELECT id FROM permiso WHERE codigo IN ('backup:ver','backup:crear','backup:descargar','platform:backup:configurar'))"
    )
    op.execute("DELETE FROM permiso WHERE codigo IN ('backup:ver','backup:crear','backup:descargar','platform:backup:configurar')")
