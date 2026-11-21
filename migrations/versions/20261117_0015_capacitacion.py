"""Capacitacion y permisos del Sprint 4.

Revision ID: 20261117_0015
Revises: 20261102_0014
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20261117_0015"
down_revision = "20261102_0014"
branch_labels = None
depends_on = None


def ident():
    return sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()"))


def company():
    return sa.Column("empresa_id", UUID(as_uuid=False), sa.ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=False)


def ref(name, table, delete="RESTRICT"):
    return sa.Column(name, UUID(as_uuid=False), sa.ForeignKey(f"{table}.id", ondelete=delete), nullable=False)


def upgrade():
    op.create_table("curso", ident(), company(), sa.Column("titulo", sa.String(200), nullable=False), sa.Column("descripcion", sa.Text()), sa.Column("categoria", sa.String(100)), sa.Column("duracion_horas", sa.Numeric(7, 2)), sa.Column("es_obligatorio", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("imagen_url", sa.Text()), sa.Column("instructor", sa.String(160)), sa.Column("nota_minima", sa.Numeric(5, 2), nullable=False, server_default="70"), sa.Column("estado", sa.String(20), nullable=False, server_default="BORRADOR"), sa.Column("creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("nota_minima BETWEEN 0 AND 100", name="ck_curso_nota_minima"))
    op.create_index("ix_curso_empresa_estado", "curso", ["empresa_id", "estado"])
    op.create_table("leccion", ident(), company(), ref("curso_id", "curso", "CASCADE"), sa.Column("titulo", sa.String(200), nullable=False), sa.Column("tipo", sa.String(20), nullable=False), sa.Column("contenido_url", sa.Text()), sa.Column("contenido_texto", sa.Text()), sa.Column("orden", sa.Integer(), nullable=False), sa.Column("duracion_minutos", sa.Integer()), sa.UniqueConstraint("curso_id", "orden", name="uq_leccion_curso_orden"), sa.CheckConstraint("tipo IN ('VIDEO','DOCUMENTO','MANUAL','QUIZ','ENLACE')", name="ck_leccion_tipo"), sa.CheckConstraint("orden > 0 AND (duracion_minutos IS NULL OR duracion_minutos >= 0)", name="ck_leccion_orden_duracion"))
    op.create_index("ix_leccion_curso_id", "leccion", ["curso_id"])
    op.create_table("inscripcion", ident(), company(), ref("curso_id", "curso"), ref("empleado_id", "empleado"), sa.Column("fecha_limite", sa.Date()), sa.Column("progreso", sa.Numeric(5, 2), nullable=False, server_default="0"), sa.Column("calificacion", sa.Numeric(5, 2)), sa.Column("aprobado", sa.Boolean(), nullable=False, server_default=sa.text("false")), sa.Column("estado", sa.String(20), nullable=False, server_default="INSCRITO"), sa.Column("certificado_url", sa.Text()), sa.Column("inscrito_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("curso_id", "empleado_id", name="uq_inscripcion_curso_empleado"), sa.CheckConstraint("progreso BETWEEN 0 AND 100 AND (calificacion IS NULL OR calificacion BETWEEN 0 AND 100)", name="ck_inscripcion_notas"), sa.CheckConstraint("estado IN ('INSCRITO','EN_CURSO','COMPLETADO','ABANDONADO','VENCIDO')", name="ck_inscripcion_estado"))
    op.create_index("ix_inscripcion_empresa_empleado", "inscripcion", ["empresa_id", "empleado_id"])
    op.create_table("progreso_leccion", ident(), company(), ref("inscripcion_id", "inscripcion", "CASCADE"), ref("leccion_id", "leccion"), sa.Column("completada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("calificacion", sa.Numeric(5, 2)), sa.UniqueConstraint("inscripcion_id", "leccion_id", name="uq_progreso_inscripcion_leccion"))
    op.create_table("empleado_habilidad", ident(), company(), ref("empleado_id", "empleado", "CASCADE"), ref("habilidad_id", "habilidad"), sa.Column("nivel", sa.String(30)), sa.Column("adquirida_en", sa.Date()), sa.UniqueConstraint("empleado_id", "habilidad_id", name="uq_empleado_habilidad"))
    grants = {"capacitacion:ver": ("ADMIN_EMPRESA", "RRHH", "JEFE_AREA"), "capacitacion:gestionar": ("ADMIN_EMPRESA", "RRHH"), "capacitacion:aprender": ("EMPLEADO", "RRHH", "JEFE_AREA"), "indicadores:ver": ("ADMIN_EMPRESA", "RRHH", "JEFE_AREA")}
    for code, roles in grants.items():
        op.execute(sa.text("INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) VALUES (:code, :module, :resource, :operation, :description) ON CONFLICT (codigo) DO NOTHING").bindparams(code=code, module="CAPACITACION" if code.startswith("capacitacion") else "REPORTES", resource="capacitacion" if code.startswith("capacitacion") else "indicadores", operation=code.split(":")[-1], description=code))
        for role in roles:
            op.execute(sa.text("INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id, p.id FROM rol r CROSS JOIN permiso p WHERE r.codigo=:role AND r.empresa_id IS NOT NULL AND p.codigo=:code ON CONFLICT DO NOTHING").bindparams(role=role, code=code))
    op.execute("INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) VALUES ('platform:capacitacion:gestionar','PLATFORM','capacitacion','gestionar','Gestionar capacitacion global'),('platform:indicadores:ver','PLATFORM','indicadores','ver','Ver indicadores globales') ON CONFLICT (codigo) DO NOTHING")
    op.execute("INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id,p.id FROM rol r CROSS JOIN permiso p WHERE r.empresa_id IS NULL AND r.codigo='SUPER_ADMIN' AND p.codigo IN ('platform:capacitacion:gestionar','platform:indicadores:ver') ON CONFLICT DO NOTHING")


def downgrade():
    op.execute("DELETE FROM rol_permiso WHERE permiso_id IN (SELECT id FROM permiso WHERE codigo IN ('capacitacion:ver','capacitacion:gestionar','capacitacion:aprender','indicadores:ver','platform:capacitacion:gestionar','platform:indicadores:ver'))")
    op.execute("DELETE FROM permiso WHERE codigo IN ('capacitacion:ver','capacitacion:gestionar','capacitacion:aprender','indicadores:ver','platform:capacitacion:gestionar','platform:indicadores:ver')")
    for table in ("empleado_habilidad", "progreso_leccion", "inscripcion", "leccion", "curso"):
        op.drop_table(table)
