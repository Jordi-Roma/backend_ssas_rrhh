"""Crear departamentos y cargos.

Revision ID: 20260830_0002
Revises: 20260825_0001
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0002"
down_revision: str | None = "20260825_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISOS = [
    (
        "departamentos:ver",
        "ORGANIZACION",
        "departamentos",
        "ver",
        "Listar y consultar departamentos de la empresa",
    ),
    (
        "departamentos:crear",
        "ORGANIZACION",
        "departamentos",
        "crear",
        "Crear departamentos de la empresa",
    ),
    (
        "departamentos:editar",
        "ORGANIZACION",
        "departamentos",
        "editar",
        "Actualizar departamentos de la empresa",
    ),
    (
        "departamentos:eliminar",
        "ORGANIZACION",
        "departamentos",
        "eliminar",
        "Eliminar departamentos sin dependencias",
    ),
    ("cargos:ver", "ORGANIZACION", "cargos", "ver", "Listar y consultar cargos de la empresa"),
    ("cargos:crear", "ORGANIZACION", "cargos", "crear", "Crear cargos de la empresa"),
    ("cargos:editar", "ORGANIZACION", "cargos", "editar", "Actualizar cargos de la empresa"),
    ("cargos:eliminar", "ORGANIZACION", "cargos", "eliminar", "Eliminar cargos sin dependencias"),
    (
        "platform:organizacion:gestionar",
        "PLATFORM",
        "organizacion",
        "gestionar",
        "Gestionar departamentos y cargos de cualquier empresa",
    ),
]


def upgrade() -> None:
    op.create_table(
        "departamento",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "nombre", name="uq_departamento_empresa_nombre"),
    )
    op.create_index("idx_departamento_empresa_id", "departamento", ["empresa_id"], unique=False)
    op.create_index(
        "uq_departamento_empresa_nombre_ci",
        "departamento",
        ["empresa_id", sa.text("lower(nombre)")],
        unique=True,
    )

    op.create_table(
        "cargo",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("empresa_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("departamento_id", sa.UUID(as_uuid=False), nullable=True),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["departamento_id"], ["departamento.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["empresa_id"], ["empresa.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empresa_id", "nombre", name="uq_cargo_empresa_nombre"),
    )
    op.create_index("idx_cargo_departamento_id", "cargo", ["departamento_id"], unique=False)
    op.create_index("idx_cargo_empresa_id", "cargo", ["empresa_id"], unique=False)
    op.create_index(
        "uq_cargo_empresa_nombre_ci",
        "cargo",
        ["empresa_id", sa.text("lower(nombre)")],
        unique=True,
    )

    for tabla in ("departamento", "cargo"):
        op.execute(
            f"CREATE TRIGGER trg_{tabla}_updated_at BEFORE UPDATE ON {tabla} "
            "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
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
        "AND p.codigo = 'platform:organizacion:gestionar' "
        "ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.empresa_id IS NOT NULL AND r.codigo = 'ADMIN_EMPRESA' "
        "AND p.codigo IN ("
        "'departamentos:ver', 'departamentos:crear', 'departamentos:editar', "
        "'departamentos:eliminar', 'cargos:ver', 'cargos:crear', 'cargos:editar', "
        "'cargos:eliminar'"
        ") ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    codigos = ", ".join(f"'{codigo}'" for codigo, *_ in PERMISOS)
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        f"(SELECT id FROM permiso WHERE codigo IN ({codigos}))"
    )
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codigos})")

    op.execute("DROP TRIGGER IF EXISTS trg_cargo_updated_at ON cargo")
    op.execute("DROP TRIGGER IF EXISTS trg_departamento_updated_at ON departamento")
    op.drop_index("uq_cargo_empresa_nombre_ci", table_name="cargo")
    op.drop_index("idx_cargo_empresa_id", table_name="cargo")
    op.drop_index("idx_cargo_departamento_id", table_name="cargo")
    op.drop_table("cargo")
    op.drop_index("uq_departamento_empresa_nombre_ci", table_name="departamento")
    op.drop_index("idx_departamento_empresa_id", table_name="departamento")
    op.drop_table("departamento")
