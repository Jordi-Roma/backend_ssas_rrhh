"""Notas internas de postulacion y permiso de alta manual de postulantes.

Agrega:

- la tabla ``postulacion_nota`` (bitacora de evaluacion por postulacion);
- el permiso ``postulantes:gestionar`` para el alta manual en el banco de talento.

El resto de endpoints del sprint reutiliza permisos ya existentes: ``vacantes:publicar``
para pausar y cerrar, ``postulaciones:ver`` / ``postulaciones:gestionar`` para puntaje y
notas, ``habilidades:gestionar`` para editar una habilidad y ``empresa:ver`` /
``platform:empresas:ver`` para el dashboard.

El CheckConstraint ``ck_vacante_estado`` ya admite 'PAUSADA' desde la migracion
7694bb109d4b, asi que no se toca.

Revision ID: 20260907_0010
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0010"
down_revision: str | None = "20260907_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISOS = [
    (
        "postulantes:gestionar",
        "RECLUTAMIENTO",
        "postulantes",
        "gestionar",
        "Registrar y mantener postulantes del banco de talento",
    ),
]
PERMISOS_EMPRESA = ("postulantes:gestionar",)
# El alcance de plataforma ya cubre este recurso con 'platform:postulantes:ver',
# creado en 20260907_0007; no se duplica un permiso equivalente.
PERMISOS_PLATAFORMA: tuple[str, ...] = ()


def upgrade() -> None:
    op.create_table(
        "postulacion_nota",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("postulacion_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("usuario_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("contenido", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["postulacion_id"], ["postulacion.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuario.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_postulacion_nota_postulacion_id", "postulacion_nota", ["postulacion_id"], unique=False
    )
    op.create_index(
        "idx_postulacion_nota_usuario_id", "postulacion_nota", ["usuario_id"], unique=False
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

    codigos_empresa = ", ".join(f"'{codigo}'" for codigo in PERMISOS_EMPRESA)
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
        "WHERE r.empresa_id IS NOT NULL AND r.codigo = 'ADMIN_EMPRESA' "
        f"AND p.codigo IN ({codigos_empresa}) ON CONFLICT DO NOTHING"
    )
    if PERMISOS_PLATAFORMA:
        codigos_plataforma = ", ".join(f"'{codigo}'" for codigo in PERMISOS_PLATAFORMA)
        op.execute(
            "INSERT INTO rol_permiso (rol_id, permiso_id) "
            "SELECT r.id, p.id FROM rol r CROSS JOIN permiso p "
            "WHERE r.empresa_id IS NULL AND r.codigo = 'SUPER_ADMIN' "
            f"AND p.codigo IN ({codigos_plataforma}) ON CONFLICT DO NOTHING"
        )


def downgrade() -> None:
    codigos = ", ".join(f"'{codigo}'" for codigo, *_ in PERMISOS)
    op.execute(
        "DELETE FROM rol_permiso WHERE permiso_id IN "
        f"(SELECT id FROM permiso WHERE codigo IN ({codigos}))"
    )
    op.execute(f"DELETE FROM permiso WHERE codigo IN ({codigos})")

    op.drop_index("idx_postulacion_nota_usuario_id", table_name="postulacion_nota")
    op.drop_index("idx_postulacion_nota_postulacion_id", table_name="postulacion_nota")
    op.drop_table("postulacion_nota")
