"""fortalecer bitacora y crear reportes personalizables

Revision ID: 20260914_0002
Revises: 75aa6ae191e4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0002"
down_revision: str | None = "75aa6ae191e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISOS = (
    "bitacora:ver_detalle",
    "bitacora:exportar",
    "reportes:ver",
    "reportes:crear",
    "reportes:editar",
    "reportes:ejecutar",
    "reportes:exportar",
    "reportes:enviar",
    "platform:bitacora:ver_detalle",
    "platform:bitacora:exportar",
    "platform:reportes:gestionar",
)


def _permiso(codigo: str) -> tuple[str, str, str]:
    partes = codigo.split(":")
    if partes[0] == "platform":
        return "PLATFORM", partes[1], partes[2]
    return ("BITACORA" if partes[0] == "bitacora" else "REPORTES", partes[0], partes[1])


def upgrade() -> None:
    op.execute(
        "INSERT INTO modulo (codigo, nombre, descripcion, icono, orden, es_core, activo) "
        "VALUES ('REPORTES', 'Reportes', 'Constructor de reportes personalizables', "
        "'chart-column', 70, TRUE, TRUE) ON CONFLICT (codigo) DO NOTHING"
    )
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
                "modulo": _permiso(codigo)[0],
                "recurso": _permiso(codigo)[1],
                "operacion": _permiso(codigo)[2],
                "descripcion": codigo,
            }
            for codigo in PERMISOS
        ],
    )
    op.execute(
        "INSERT INTO empresa_modulo (empresa_id, modulo_id, habilitado, fecha_habilitacion) "
        "SELECT e.id, m.id, TRUE, now() FROM empresa e CROSS JOIN modulo m "
        "WHERE m.codigo = 'REPORTES' ON CONFLICT (empresa_id, modulo_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r "
        "CROSS JOIN permiso p WHERE r.codigo = 'ADMIN_EMPRESA' AND r.empresa_id IS NOT NULL "
        "AND p.codigo IN ('bitacora:ver_detalle','bitacora:exportar','reportes:ver',"
        "'reportes:crear','reportes:editar','reportes:ejecutar','reportes:exportar',"
        "'reportes:enviar') ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r "
        "CROSS JOIN permiso p WHERE r.codigo = 'SUPER_ADMIN' AND r.empresa_id IS NULL "
        "AND p.codigo LIKE 'platform:%' ON CONFLICT DO NOTHING"
    )

    op.create_table(
        "reporte_definicion",
        sa.Column("id", sa.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("usuario_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("fuente", sa.String(60), nullable=False),
        sa.Column("columnas", postgresql.JSONB(), nullable=False),
        sa.Column("filtros", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("orden", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("fecha_registro", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("fecha_actualizacion", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "nombre", name="uq_reporte_definicion_empresa_nombre"),
    )
    op.create_index("idx_reporte_definicion_empresa", "reporte_definicion", ["empresa_id"])
    op.create_table(
        "reporte_ejecucion",
        sa.Column("id", sa.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("reporte_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("usuario_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("formato", sa.String(20), nullable=False),
        sa.Column("filtros_aplicados", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("cantidad_registros", sa.Integer(), nullable=True),
        sa.Column("fecha_inicio", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("fecha_fin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporte_id"], ["reporte_definicion.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_reporte_ejecucion_empresa_fecha", "reporte_ejecucion", ["empresa_id", "fecha_inicio"])

    op.drop_constraint("bitacora_empresa_id_fkey", "bitacora", type_="foreignkey")
    op.create_foreign_key(
        "bitacora_empresa_id_fkey", "bitacora", "empresa", ["empresa_id"], ["id"], ondelete="SET NULL"
    )
    op.execute(
        "CREATE FUNCTION proteger_bitacora() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'La bitacora es inmutable'; END; $$"
    )
    op.execute(
        "CREATE TRIGGER trg_bitacora_inmutable BEFORE UPDATE OR DELETE ON bitacora "
        "FOR EACH ROW EXECUTE FUNCTION proteger_bitacora()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_bitacora_inmutable ON bitacora")
    op.execute("DROP FUNCTION IF EXISTS proteger_bitacora()")
    op.drop_constraint("bitacora_empresa_id_fkey", "bitacora", type_="foreignkey")
    op.create_foreign_key(
        "bitacora_empresa_id_fkey", "bitacora", "empresa", ["empresa_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_table("reporte_ejecucion")
    op.drop_table("reporte_definicion")
    op.execute("DELETE FROM permiso WHERE codigo = ANY(ARRAY[" + ",".join(f"'{p}'" for p in PERMISOS) + "])")
    op.execute("DELETE FROM modulo WHERE codigo = 'REPORTES'")
