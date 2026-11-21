"""Perfil de habilidades y notificaciones persistentes.

Revision ID: 20261121_0016
Revises: 20261117_0015
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20261121_0016"
down_revision = "20261117_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("curso", sa.Column("habilidad_id", UUID(as_uuid=False), sa.ForeignKey("habilidad.id", ondelete="SET NULL")))
    op.add_column("empleado_habilidad", sa.Column("fecha_evaluacion", sa.DateTime(timezone=True)))
    op.add_column("empleado_habilidad", sa.Column("certificado_por", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")))
    op.add_column("empleado_habilidad", sa.Column("curso_id", UUID(as_uuid=False), sa.ForeignKey("curso.id", ondelete="SET NULL")))
    op.create_table(
        "notificacion",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("empresa_id", UUID(as_uuid=False), sa.ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tipo", sa.String(40), nullable=False),
        sa.Column("titulo", sa.String(160), nullable=False),
        sa.Column("mensaje", sa.Text(), nullable=False),
        sa.Column("ruta", sa.String(255)),
        sa.Column("evento_clave", sa.String(160), nullable=False),
        sa.Column("fecha", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("leida_en", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("empresa_id", "usuario_id", "evento_clave", name="uq_notificacion_evento_usuario"),
    )
    op.create_index("ix_notificacion_bandeja", "notificacion", ["empresa_id", "usuario_id", "fecha"])
    op.create_table(
        "notificacion_dispositivo",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("empresa_id", UUID(as_uuid=False), sa.ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False),
        sa.Column("usuario_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(512), nullable=False, unique=True),
        sa.Column("actualizado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notificacion_dispositivo_usuario", "notificacion_dispositivo", ["empresa_id", "usuario_id"])


def downgrade():
    op.drop_index("ix_notificacion_dispositivo_usuario", table_name="notificacion_dispositivo")
    op.drop_table("notificacion_dispositivo")
    op.drop_index("ix_notificacion_bandeja", table_name="notificacion")
    op.drop_table("notificacion")
    op.drop_column("empleado_habilidad", "curso_id")
    op.drop_column("empleado_habilidad", "certificado_por")
    op.drop_column("empleado_habilidad", "fecha_evaluacion")
    op.drop_column("curso", "habilidad_id")
