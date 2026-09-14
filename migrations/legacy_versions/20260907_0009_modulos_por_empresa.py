"""Catalogo de modulos y habilitacion por empresa."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0009"
down_revision: str | None = "20260907_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# El codigo coincide con permiso.modulo: es la bisagra que permite filtrar los
# permisos efectivos sin tocar los guards de cada endpoint.
MODULOS = [
    ("EMPRESAS", "Mi empresa", "Datos y configuracion de la propia empresa", "building", 10, True),
    ("USUARIOS", "Usuarios", "Altas, bajas y accesos de usuarios", "users", 20, True),
    ("ROLES", "Roles y permisos", "Definicion de roles y sus permisos", "shield", 30, True),
    ("BITACORA", "Bitacora", "Auditoria de eventos del sistema", "history", 40, True),
    (
        "ORGANIZACION",
        "Organizacion",
        "Estructura de departamentos y cargos",
        "sitemap",
        50,
        False,
    ),
    (
        "RECLUTAMIENTO",
        "Reclutamiento",
        "Vacantes, postulantes y tablero de seleccion",
        "briefcase",
        60,
        False,
    ),
]

PERMISOS = [
    (
        "platform:modulos:ver",
        "PLATFORM",
        "modulos",
        "ver",
        "Consultar los modulos habilitados de cualquier empresa",
    ),
    (
        "platform:modulos:gestionar",
        "PLATFORM",
        "modulos",
        "gestionar",
        "Habilitar o deshabilitar modulos por empresa",
    ),
]


def upgrade() -> None:
    op.create_table(
        "modulo",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("codigo", sa.String(60), nullable=False, unique=True),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("icono", sa.String(60), nullable=True),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("es_core", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "empresa_modulo",
        sa.Column(
            "empresa_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("empresa.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "modulo_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("modulo.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("habilitado", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("fecha_habilitacion", sa.DateTime(timezone=True), nullable=True),
        sa.Column("habilitado_por_id", sa.dialects.postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_empresa_modulo_empresa_id", "empresa_modulo", ["empresa_id"])

    modulo_table = sa.table(
        "modulo",
        sa.column("codigo", sa.String),
        sa.column("nombre", sa.String),
        sa.column("descripcion", sa.String),
        sa.column("icono", sa.String),
        sa.column("orden", sa.Integer),
        sa.column("es_core", sa.Boolean),
    )
    op.bulk_insert(
        modulo_table,
        [
            {
                "codigo": codigo,
                "nombre": nombre,
                "descripcion": descripcion,
                "icono": icono,
                "orden": orden,
                "es_core": es_core,
            }
            for codigo, nombre, descripcion, icono, orden, es_core in MODULOS
        ],
    )

    # Las empresas existentes conservan todo lo que ya usaban: los modulos opcionales
    # nacen habilitados para no revocar accesos con el despliegue.
    op.execute(
        "INSERT INTO empresa_modulo (empresa_id, modulo_id, habilitado, fecha_habilitacion) "
        "SELECT e.id, m.id, TRUE, now() FROM empresa e CROSS JOIN modulo m "
        "WHERE m.es_core = FALSE ON CONFLICT DO NOTHING"
    )

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
        "AND p.codigo IN ('platform:modulos:ver', 'platform:modulos:gestionar') "
        "ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{codigo}'" for codigo, *_ in PERMISOS)
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        f"(SELECT id FROM permiso WHERE codigo IN ({codes}))"
    )
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codes})")
    op.drop_index("idx_empresa_modulo_empresa_id", table_name="empresa_modulo")
    op.drop_table("empresa_modulo")
    op.drop_table("modulo")
