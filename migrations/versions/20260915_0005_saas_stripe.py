"""modelo saas multiempresa y stripe sandbox

Revision ID: 20260915_0005
Revises: 20260914_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_0005"
down_revision: str | None = "20260914_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISOS = (
    "platform:planes:ver", "platform:planes:crear", "platform:planes:editar",
    "platform:suscripciones:ver", "platform:suscripciones:gestionar",
    "platform:suscripciones:ajustar", "suscripcion:ver", "suscripcion:contratar",
    "suscripcion:gestionar_pago",
)


def upgrade() -> None:
    op.add_column("plan_suscripcion", sa.Column("descripcion", sa.Text()))
    op.add_column("plan_suscripcion", sa.Column("moneda", sa.String(3), server_default="USD", nullable=False))
    op.add_column("plan_suscripcion", sa.Column("max_usuarios", sa.Integer(), server_default="5", nullable=False))
    op.add_column("plan_suscripcion", sa.Column("max_vacantes_activas", sa.Integer(), server_default="5", nullable=False))
    op.add_column("plan_suscripcion", sa.Column("max_almacenamiento_mb", sa.Integer(), server_default="250", nullable=False))
    op.add_column("plan_suscripcion", sa.Column("stripe_price_id", sa.String(120)))
    op.add_column("plan_suscripcion", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.add_column("plan_suscripcion", sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False))
    op.create_unique_constraint("uq_plan_stripe_price", "plan_suscripcion", ["stripe_price_id"])
    op.execute("UPDATE plan_suscripcion SET max_usuarios=max_empleados WHERE max_empleados IS NOT NULL")
    op.execute(
        "UPDATE plan_suscripcion SET max_usuarios=5, max_empleados=5, "
        "max_vacantes_activas=5, max_almacenamiento_mb=250 "
        "WHERE lower(nombre) IN ('basico', 'básico')"
    )
    op.execute(
        "INSERT INTO plan_suscripcion "
        "(nombre, descripcion, precio_mensual, moneda, max_empleados, max_usuarios, "
        "max_vacantes_activas, max_almacenamiento_mb, modulos, activo) VALUES "
        "('Profesional', 'Operación completa para equipos de RRHH', 49, 'USD', 25, 25, "
        "30, 2048, '[\"ORGANIZACION\",\"RECLUTAMIENTO\"]'::jsonb, TRUE), "
        "('Empresarial', 'Capacidad ampliada y todos los módulos', 149, 'USD', 100, 100, "
        "150, 10240, '[\"ORGANIZACION\",\"RECLUTAMIENTO\"]'::jsonb, TRUE) "
        "ON CONFLICT (nombre) DO NOTHING"
    )

    for name, type_ in (
        ("periodo_prueba_hasta", sa.Date()),
        ("stripe_customer_id", sa.String(120)),
        ("stripe_subscription_id", sa.String(120)),
        ("stripe_checkout_session_id", sa.String(120)),
        ("fecha_ultimo_pago", sa.DateTime(timezone=True)),
        ("fecha_proximo_cobro", sa.DateTime(timezone=True)),
        ("creado_por_id", sa.UUID(as_uuid=False)),
        ("created_at", sa.DateTime(timezone=True)),
        ("updated_at", sa.DateTime(timezone=True)),
    ):
        kwargs = {"server_default": sa.text("now()"), "nullable": False} if name in {"created_at", "updated_at"} else {}
        op.add_column("suscripcion", sa.Column(name, type_, **kwargs))
    op.add_column("suscripcion", sa.Column("cancelar_al_fin_periodo", sa.Boolean(), server_default="false", nullable=False))
    op.create_foreign_key("suscripcion_creado_por_id_fkey", "suscripcion", "usuario", ["creado_por_id"], ["id"], ondelete="SET NULL")
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT empresa_id FROM suscripcion GROUP BY empresa_id "
        "HAVING COUNT(*) > 1) THEN RAISE EXCEPTION "
        "'Hay empresas con más de una suscripción; resuelva los duplicados antes de migrar'; "
        "END IF; END $$"
    )
    op.create_unique_constraint("uq_suscripcion_empresa", "suscripcion", ["empresa_id"])
    op.create_unique_constraint("uq_suscripcion_stripe_customer", "suscripcion", ["stripe_customer_id"])
    op.create_unique_constraint("uq_suscripcion_stripe_subscription", "suscripcion", ["stripe_subscription_id"])
    op.create_unique_constraint("uq_suscripcion_stripe_checkout", "suscripcion", ["stripe_checkout_session_id"])

    op.create_table(
        "plan_modulo",
        sa.Column("plan_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("modulo_id", sa.UUID(as_uuid=False), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["plan_suscripcion.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["modulo_id"], ["modulo.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_id", "modulo_id"),
        sa.UniqueConstraint("plan_id", "modulo_id", name="uq_plan_modulo"),
    )
    op.create_table(
        "stripe_evento",
        sa.Column("id", sa.UUID(as_uuid=False), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("stripe_event_id", sa.String(120), nullable=False),
        sa.Column("tipo", sa.String(120), nullable=False),
        sa.Column("estado_procesamiento", sa.String(30), nullable=False),
        sa.Column("fecha_recepcion", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("fecha_procesamiento", sa.DateTime(timezone=True)),
        sa.Column("intentos", sa.Integer(), server_default="1", nullable=False),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_event_id"),
    )
    op.execute(
        "INSERT INTO plan_modulo (plan_id, modulo_id) SELECT p.id, m.id FROM plan_suscripcion p "
        "JOIN modulo m ON m.codigo IN (SELECT jsonb_array_elements_text(p.modulos)) ON CONFLICT DO NOTHING"
    )
    op.execute(
        "INSERT INTO suscripcion (empresa_id, plan_id, estado, fecha_inicio) "
        "SELECT e.id, p.id, 'ACTIVA', CURRENT_DATE FROM empresa e CROSS JOIN LATERAL "
        "(SELECT id FROM plan_suscripcion WHERE activo=TRUE ORDER BY precio_mensual, nombre LIMIT 1) p "
        "WHERE NOT EXISTS (SELECT 1 FROM suscripcion s WHERE s.empresa_id=e.id)"
    )
    op.execute(
        "UPDATE empresa_modulo em SET habilitado = m.es_core OR EXISTS ("
        "SELECT 1 FROM suscripcion s JOIN plan_modulo pm ON pm.plan_id=s.plan_id "
        "WHERE s.empresa_id=em.empresa_id AND pm.modulo_id=em.modulo_id) "
        "FROM modulo m WHERE m.id=em.modulo_id"
    )
    permiso = sa.table("permiso", sa.column("codigo", sa.String), sa.column("modulo", sa.String), sa.column("recurso", sa.String), sa.column("operacion", sa.String), sa.column("descripcion", sa.String))
    op.bulk_insert(permiso, [{"codigo": c, "modulo": "PLATFORM" if c.startswith("platform:") else "SUSCRIPCION", "recurso": c.split(":")[-2], "operacion": c.split(":")[-1], "descripcion": c} for c in PERMISOS])
    op.execute("INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id,p.id FROM rol r CROSS JOIN permiso p WHERE r.codigo='SUPER_ADMIN' AND r.empresa_id IS NULL AND p.codigo LIKE 'platform:%' ON CONFLICT DO NOTHING")
    op.execute("INSERT INTO rol_permiso (rol_id, permiso_id) SELECT r.id,p.id FROM rol r CROSS JOIN permiso p WHERE r.codigo='ADMIN_EMPRESA' AND r.empresa_id IS NOT NULL AND p.codigo LIKE 'suscripcion:%' ON CONFLICT DO NOTHING")


def downgrade() -> None:
    op.drop_table("stripe_evento")
    op.drop_table("plan_modulo")
    op.execute("DELETE FROM permiso WHERE codigo = ANY(ARRAY[" + ",".join(f"'{c}'" for c in PERMISOS) + "])")
    for constraint in ("uq_suscripcion_stripe_checkout", "uq_suscripcion_stripe_subscription", "uq_suscripcion_stripe_customer", "uq_suscripcion_empresa"):
        op.drop_constraint(constraint, "suscripcion", type_="unique")
    op.drop_constraint("suscripcion_creado_por_id_fkey", "suscripcion", type_="foreignkey")
    for name in ("cancelar_al_fin_periodo", "updated_at", "created_at", "creado_por_id", "fecha_proximo_cobro", "fecha_ultimo_pago", "stripe_checkout_session_id", "stripe_subscription_id", "stripe_customer_id", "periodo_prueba_hasta"):
        op.drop_column("suscripcion", name)
    op.drop_constraint("uq_plan_stripe_price", "plan_suscripcion", type_="unique")
    for name in ("updated_at", "created_at", "stripe_price_id", "max_almacenamiento_mb", "max_vacantes_activas", "max_usuarios", "moneda", "descripcion"):
        op.drop_column("plan_suscripcion", name)
