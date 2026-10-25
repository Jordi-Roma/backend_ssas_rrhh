"""Sprint 3: legajo, contratos, asistencia, ausencias y nomina.

Revision ID: 20261024_0011
Revises: 20261006_0010
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20261024_0011"
down_revision = "20261006_0010"
branch_labels = None
depends_on = None


def _id():
    return sa.Column(
        "id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _empresa():
    return sa.Column(
        "empresa_id",
        UUID(as_uuid=False),
        sa.ForeignKey("empresa.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _empleado():
    return sa.Column(
        "empleado_id",
        UUID(as_uuid=False),
        sa.ForeignKey("empleado.id", ondelete="RESTRICT"),
        nullable=False,
    )


PERMISOS = {
    "personal:ver": "ORGANIZACION",
    "personal:gestionar": "ORGANIZACION",
    "personal:mi": "ORGANIZACION",
    "personal:ver_equipo": "ORGANIZACION",
    "asistencia:ver": "ORGANIZACION",
    "asistencia:ver_equipo": "ORGANIZACION",
    "asistencia:marcar": "ORGANIZACION",
    "asistencia:mi": "ORGANIZACION",
    "asistencia:solicitar_ajuste": "ORGANIZACION",
    "asistencia:aprobar_ajuste": "ORGANIZACION",
    "asistencia:autorizar_extra": "ORGANIZACION",
    "ausencias:gestionar": "ORGANIZACION",
    "ausencias:aprobar": "ORGANIZACION",
    "ausencias:solicitar": "ORGANIZACION",
    "ausencias:mi": "ORGANIZACION",
    "nomina:ver": "ORGANIZACION",
    "nomina:gestionar": "ORGANIZACION",
    "boletas:ver": "ORGANIZACION",
    "boletas:mi": "ORGANIZACION",
}

GRANTS = {
    "RRHH": (
        "personal:ver",
        "personal:gestionar",
        "personal:mi",
        "asistencia:ver",
        "asistencia:mi",
        "asistencia:marcar",
        "asistencia:solicitar_ajuste",
        "asistencia:aprobar_ajuste",
        "asistencia:autorizar_extra",
        "ausencias:gestionar",
        "ausencias:aprobar",
        "ausencias:solicitar",
        "ausencias:mi",
        "nomina:ver",
        "nomina:gestionar",
        "boletas:ver",
        "boletas:mi",
    ),
    "JEFE_AREA": (
        "personal:mi",
        "personal:ver_equipo",
        "asistencia:ver_equipo",
        "asistencia:mi",
        "asistencia:marcar",
        "asistencia:solicitar_ajuste",
        "asistencia:aprobar_ajuste",
        "ausencias:aprobar",
        "ausencias:solicitar",
        "ausencias:mi",
        "boletas:mi",
    ),
    "EMPLEADO": (
        "personal:mi",
        "asistencia:marcar",
        "asistencia:solicitar_ajuste",
        "asistencia:mi",
        "ausencias:solicitar",
        "ausencias:mi",
        "boletas:mi",
    ),
}


def upgrade() -> None:
    op.create_table(
        "contrato",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "cargo_id",
            UUID(as_uuid=False),
            sa.ForeignKey("cargo.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "departamento_id",
            UUID(as_uuid=False),
            sa.ForeignKey("departamento.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "jefe_directo_id",
            UUID(as_uuid=False),
            sa.ForeignKey("empleado.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "contrato_anterior_id",
            UUID(as_uuid=False),
            sa.ForeignKey("contrato.id", ondelete="RESTRICT"),
        ),
        sa.Column("numero_contrato", sa.String(80), nullable=False),
        sa.Column("tipo_contrato", sa.String(30), nullable=False),
        sa.Column("modalidad", sa.String(30), nullable=False),
        sa.Column("jornada", sa.String(30), nullable=False),
        sa.Column("hora_entrada_programada", sa.Time(), nullable=False),
        sa.Column("horas_jornada", sa.Numeric(4, 2), nullable=False),
        sa.Column("minutos_descanso", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("salario_basico", sa.Numeric(14, 2), nullable=False),
        sa.Column("moneda", sa.String(3), nullable=False, server_default="BOB"),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date()),
        sa.Column("motivo_cambio", sa.Text()),
        sa.Column("estado", sa.String(20), nullable=False, server_default="VIGENTE"),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("empresa_id", "numero_contrato", name="uq_contrato_numero_empresa"),
        sa.CheckConstraint("salario_basico > 0", name="ck_contrato_salario"),
        sa.CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_contrato_fechas"
        ),
    )
    op.create_index(
        "idx_contrato_empleado_fecha", "contrato", ["empresa_id", "empleado_id", "fecha_inicio"]
    )
    op.create_index(
        "uq_contrato_vigente_empleado",
        "contrato",
        ["empleado_id"],
        unique=True,
        postgresql_where=sa.text("estado = 'VIGENTE'"),
    )
    op.create_table(
        "documento_empleado",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("ruta_privada", sa.Text(), nullable=False),
        sa.Column("tipo_mime", sa.String(100), nullable=False),
        sa.Column("tamano_bytes", sa.Integer(), nullable=False),
        sa.Column("fecha_emision", sa.Date()),
        sa.Column("fecha_vencimiento", sa.Date()),
        sa.Column(
            "fecha_carga", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_documento_empleado", "documento_empleado", ["empresa_id", "empleado_id"])
    op.create_table(
        "tipo_ausencia",
        _id(),
        _empresa(),
        sa.Column("codigo", sa.String(40), nullable=False),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("es_remunerado", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("descuenta_vacacion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("dias_maximos_anio", sa.Integer()),
        sa.Column("requiere_aprobacion", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("requiere_documento", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activo", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("empresa_id", "codigo", name="uq_tipo_ausencia_codigo"),
    )
    op.create_table(
        "saldo_vacacion",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column("gestion", sa.Integer(), nullable=False),
        sa.Column("dias_asignados", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dias_usados", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "empresa_id", "empleado_id", "gestion", name="uq_saldo_vacacion_gestion"
        ),
        sa.CheckConstraint(
            "dias_asignados >= 0 AND dias_usados >= 0 AND dias_usados <= dias_asignados",
            name="ck_saldo_vacacion_no_negativo",
        ),
    )
    op.create_table(
        "solicitud_ausencia",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "tipo_ausencia_id",
            UUID(as_uuid=False),
            sa.ForeignKey("tipo_ausencia.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
        sa.Column("fecha_fin", sa.Date(), nullable=False),
        sa.Column("dias_solicitados", sa.Integer(), nullable=False),
        sa.Column("dias_descontados", sa.Integer()),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("documento_url", sa.Text()),
        sa.Column("estado", sa.String(20), nullable=False, server_default="PENDIENTE"),
        sa.Column("observacion_jefe", sa.Text()),
        sa.Column(
            "resuelto_por_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")
        ),
        sa.Column("resuelto_en", sa.DateTime(timezone=True)),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "fecha_fin >= fecha_inicio AND dias_solicitados > 0",
            name="ck_solicitud_ausencia_fechas",
        ),
        sa.CheckConstraint(
            "dias_descontados IS NULL OR (dias_descontados > 0 AND dias_descontados <= dias_solicitados)",
            name="ck_solicitud_ausencia_descuento",
        ),
    )
    op.create_index(
        "idx_solicitud_ausencia_empresa_estado", "solicitud_ausencia", ["empresa_id", "estado"]
    )
    op.create_table(
        "asistencia",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("hora_entrada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hora_salida", sa.DateTime(timezone=True)),
        sa.Column("lat_entrada", sa.Numeric(9, 6)),
        sa.Column("lon_entrada", sa.Numeric(9, 6)),
        sa.Column("lat_salida", sa.Numeric(9, 6)),
        sa.Column("lon_salida", sa.Numeric(9, 6)),
        sa.Column("horas_trabajadas", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("horas_extra", sa.Numeric(8, 2), nullable=False, server_default="0"),
        sa.Column("minutos_retraso", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origen", sa.String(20), nullable=False),
        sa.UniqueConstraint(
            "empresa_id", "empleado_id", "fecha", name="uq_asistencia_empleado_fecha"
        ),
        sa.CheckConstraint(
            "horas_trabajadas >= 0 AND horas_extra >= 0 AND minutos_retraso >= 0",
            name="ck_asistencia_tiempos",
        ),
    )
    op.create_table(
        "solicitud_correccion_asistencia",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "asistencia_id",
            UUID(as_uuid=False),
            sa.ForeignKey("asistencia.id", ondelete="RESTRICT"),
        ),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("nueva_entrada", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nueva_salida", sa.DateTime(timezone=True), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="PENDIENTE"),
        sa.Column("observacion_jefe", sa.Text()),
        sa.Column(
            "resuelto_por_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")
        ),
        sa.Column("resuelto_en", sa.DateTime(timezone=True)),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("nueva_salida > nueva_entrada", name="ck_correccion_asistencia_horas"),
    )
    op.create_index(
        "uq_correccion_asistencia_pendiente",
        "solicitud_correccion_asistencia",
        ["empresa_id", "empleado_id", "fecha"],
        unique=True,
        postgresql_where=sa.text("estado = 'PENDIENTE'"),
    )
    op.create_table(
        "autorizacion_horas_extra",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "asistencia_id",
            UUID(as_uuid=False),
            sa.ForeignKey("asistencia.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("horas_solicitadas", sa.Numeric(8, 2), nullable=False),
        sa.Column("motivo", sa.Text(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="JEFE_PENDIENTE"),
        sa.Column("jefe_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")),
        sa.Column("jefe_en", sa.DateTime(timezone=True)),
        sa.Column("rrhh_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")),
        sa.Column("rrhh_en", sa.DateTime(timezone=True)),
        sa.Column("monto_autorizado", sa.Numeric(14, 2)),
        sa.Column("referencia_calculo", sa.String(160)),
        sa.Column("observacion", sa.Text()),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("asistencia_id", name="uq_autorizacion_extra_asistencia"),
        sa.CheckConstraint(
            "horas_solicitadas > 0 AND (monto_autorizado IS NULL OR monto_autorizado > 0)",
            name="ck_autorizacion_extra_positiva",
        ),
    )
    op.create_table(
        "estructura_salarial",
        _id(),
        _empresa(),
        sa.Column("nombre", sa.String(120), nullable=False),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("empresa_id", "nombre", name="uq_estructura_salarial_nombre"),
    )
    op.create_table(
        "regla_salarial",
        _id(),
        _empresa(),
        sa.Column(
            "estructura_id",
            UUID(as_uuid=False),
            sa.ForeignKey("estructura_salarial.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("codigo", sa.String(60), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("secuencia", sa.Integer(), nullable=False),
        sa.Column("tipo_calculo", sa.String(20), nullable=False),
        sa.Column("monto_fijo", sa.Numeric(14, 2)),
        sa.Column("porcentaje", sa.Numeric(8, 4)),
        sa.Column("base_calculo", sa.String(40)),
        sa.Column("formula", sa.Text()),
        sa.Column("condicion", sa.String(100)),
        sa.Column("parametro_codigo", sa.String(80)),
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("estructura_id", "codigo", name="uq_regla_salarial_codigo"),
        sa.UniqueConstraint("estructura_id", "secuencia", name="uq_regla_salarial_secuencia"),
    )
    op.create_table(
        "periodo_nomina",
        _id(),
        _empresa(),
        sa.Column("gestion", sa.Integer(), nullable=False),
        sa.Column("mes", sa.Integer(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ABIERTO"),
        sa.Column("calculado_en", sa.DateTime(timezone=True)),
        sa.Column("aprobado_en", sa.DateTime(timezone=True)),
        sa.Column(
            "aprobado_por_id", UUID(as_uuid=False), sa.ForeignKey("usuario.id", ondelete="SET NULL")
        ),
        sa.UniqueConstraint("empresa_id", "gestion", "mes", name="uq_periodo_nomina_mes"),
        sa.CheckConstraint("mes BETWEEN 1 AND 12", name="ck_periodo_nomina_mes"),
    )
    op.create_table(
        "impuesto_empleado",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "periodo_id",
            UUID(as_uuid=False),
            sa.ForeignKey("periodo_nomina.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("rc_iva_retenido", sa.Numeric(14, 2), nullable=False),
        sa.Column("datos_tributarios", JSONB(), nullable=True),
        sa.Column("referencia_planilla", sa.String(160), nullable=False),
        sa.Column(
            "registrado_por_id",
            UUID(as_uuid=False),
            sa.ForeignKey("usuario.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "registrado_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("periodo_id", "empleado_id", name="uq_impuesto_empleado_periodo"),
        sa.CheckConstraint("rc_iva_retenido >= 0", name="ck_impuesto_empleado_no_negativo"),
    )
    op.create_table(
        "haber_proporcional",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "periodo_id",
            UUID(as_uuid=False),
            sa.ForeignKey("periodo_nomina.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dias_pagados", sa.Integer(), nullable=False),
        sa.Column("haber_basico_pagado", sa.Numeric(14, 2), nullable=False),
        sa.Column("referencia_calculo", sa.String(160), nullable=False),
        sa.Column(
            "registrado_por_id",
            UUID(as_uuid=False),
            sa.ForeignKey("usuario.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("registrado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("periodo_id", "empleado_id", name="uq_haber_proporcional_periodo"),
        sa.CheckConstraint("dias_pagados BETWEEN 1 AND 31", name="ck_haber_proporcional_dias"),
        sa.CheckConstraint("haber_basico_pagado > 0", name="ck_haber_proporcional_monto"),
    )
    op.create_table(
        "boleta_pago",
        _id(),
        _empresa(),
        _empleado(),
        sa.Column(
            "periodo_id",
            UUID(as_uuid=False),
            sa.ForeignKey("periodo_nomina.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "contrato_id",
            UUID(as_uuid=False),
            sa.ForeignKey("contrato.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dias_trabajados", sa.Integer(), nullable=False),
        sa.Column("salario_basico", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_ganado", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_descuentos", sa.Numeric(14, 2), nullable=False),
        sa.Column("liquido_pagable", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_aportes_patronales", sa.Numeric(14, 2), nullable=False),
        sa.UniqueConstraint("periodo_id", "empleado_id", name="uq_boleta_periodo_empleado"),
    )
    op.create_table(
        "boleta_detalle",
        _id(),
        _empresa(),
        sa.Column(
            "boleta_id",
            UUID(as_uuid=False),
            sa.ForeignKey("boleta_pago.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "regla_id", UUID(as_uuid=False), sa.ForeignKey("regla_salarial.id", ondelete="SET NULL")
        ),
        sa.Column("codigo", sa.String(60), nullable=False),
        sa.Column("nombre", sa.String(150), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("cantidad", sa.Numeric(12, 2), nullable=False, server_default="1"),
        sa.Column("monto", sa.Numeric(14, 2), nullable=False),
    )
    op.create_index("idx_boleta_detalle_boleta", "boleta_detalle", ["boleta_id"])

    for code, name, paid, subtract, require_doc in (
        ("VACACION", "Vacacion", True, True, False),
        ("PERMISO", "Permiso", True, False, False),
        ("LICENCIA_MEDICA", "Licencia medica", True, False, True),
        ("SIN_GOCE", "Sin goce", False, False, False),
    ):
        op.execute(
            sa.text(
                "INSERT INTO tipo_ausencia (empresa_id, codigo, nombre, es_remunerado, descuenta_vacacion, requiere_documento) "
                "SELECT id, :codigo, :nombre, :pagado, :descuenta, :documento FROM empresa ON CONFLICT DO NOTHING"
            ).bindparams(
                codigo=code, nombre=name, pagado=paid, descuenta=subtract, documento=require_doc
            )
        )

    op.execute(
        "INSERT INTO estructura_salarial (empresa_id, nombre) "
        "SELECT id, 'Nomina general' FROM empresa ON CONFLICT DO NOTHING"
    )
    for code, name, kind, sequence, calculation, basis, parameter in (
        ("SALARIO_BASICO", "Salario basico", "INGRESO", 10, "BASE", None, None),
        ("HORAS_EXTRA", "Horas extraordinarias autorizadas", "INGRESO", 15, "EXTERNO", None, None),
        (
            "AFP",
            "Aporte laboral SIP",
            "DESCUENTO",
            20,
            "PORCENTAJE",
            "TOTAL_GANADO",
            "AFP_LABORAL_BO",
        ),
        (
            "SOLIDARIO",
            "Aporte solidario laboral",
            "DESCUENTO",
            30,
            "PORCENTAJE",
            "TOTAL_GANADO",
            "SOLIDARIO_LABORAL_BO",
        ),
        ("ANS", "Aporte Nacional Solidario", "DESCUENTO", 35, "TRAMOS_ANS_BO", None, None),
        ("RC_IVA", "RC-IVA planilla tributaria", "DESCUENTO", 40, "EXTERNO", None, None),
        (
            "CNS_PATRONAL",
            "Caja Nacional de Salud",
            "PATRONAL",
            50,
            "PORCENTAJE",
            "TOTAL_GANADO",
            "CNS_PATRONAL_BO",
        ),
        (
            "VIVIENDA_PATRONAL",
            "Vivienda patronal",
            "PATRONAL",
            60,
            "PORCENTAJE",
            "TOTAL_GANADO",
            "VIVIENDA_PATRONAL_BO",
        ),
        (
            "RIESGO_PATRONAL",
            "Riesgo profesional",
            "PATRONAL",
            70,
            "PORCENTAJE",
            "TOTAL_GANADO",
            "RIESGO_PATRONAL_BO",
        ),
        (
            "SOLIDARIO_PATRONAL",
            "Solidario patronal",
            "PATRONAL",
            80,
            "PORCENTAJE",
            "TOTAL_GANADO",
            "SOLIDARIO_PATRONAL_BO",
        ),
    ):
        op.execute(
            sa.text(
                "INSERT INTO regla_salarial (empresa_id, estructura_id, codigo, nombre, tipo, secuencia, tipo_calculo, base_calculo, parametro_codigo) "
                "SELECT s.empresa_id, s.id, :codigo, :nombre, :tipo, :secuencia, :calculo, :base, :parametro "
                "FROM estructura_salarial s WHERE s.nombre = 'Nomina general' ON CONFLICT DO NOTHING"
            ).bindparams(
                codigo=code,
                nombre=name,
                tipo=kind,
                secuencia=sequence,
                calculo=calculation,
                base=basis,
                parametro=parameter,
            )
        )
        if parameter:
            op.execute(
                sa.text(
                    "INSERT INTO parametro_legal (codigo, nombre, descripcion, tipo_valor, pais) "
                    "VALUES (:codigo, :nombre, 'Tasa salarial verificada por vigencia', 'PORCENTAJE', 'BO') "
                    "ON CONFLICT (codigo) DO NOTHING"
                ).bindparams(codigo=parameter, nombre=name)
            )

    op.execute(
        "INSERT INTO parametro_legal (codigo, nombre, descripcion, tipo_valor, pais) "
        "VALUES ('SMN_BO', 'Salario minimo nacional', "
        "'Monto legal para planilla RC-IVA por vigencia', 'MONTO', 'BO') "
        "ON CONFLICT (codigo) DO NOTHING"
    )
    for code, module in PERMISOS.items():
        for full_code, target_module in ((code, module), (f"platform:{code}", "PLATFORM")):
            resource, operation = code.split(":", 1)
            op.execute(
                sa.text(
                    "INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) "
                    "VALUES (:codigo, :modulo, :recurso, :operacion, :descripcion) ON CONFLICT (codigo) DO NOTHING"
                ).bindparams(
                    codigo=full_code,
                    modulo=target_module,
                    recurso=resource,
                    operacion=operation,
                    descripcion=full_code,
                )
            )
    op.execute(
        "INSERT INTO permiso (codigo, modulo, recurso, operacion, descripcion) "
        "VALUES ('platform:nomina:parametros', 'PLATFORM', 'nomina', 'parametros', "
        "'Configurar tasas legales de nomina') ON CONFLICT (codigo) DO NOTHING"
    )
    for role, codes in {"ADMIN_EMPRESA": tuple(PERMISOS), **GRANTS}.items():
        for code in codes:
            op.execute(
                sa.text(
                    "INSERT INTO rol_permiso (rol_id, permiso_id) "
                    "SELECT r.id, p.id FROM rol r JOIN permiso p ON p.codigo = :codigo "
                    "WHERE r.codigo = :rol AND r.empresa_id IS NOT NULL ON CONFLICT DO NOTHING"
                ).bindparams(codigo=code, rol=role)
            )
    for code in PERMISOS:
        op.execute(
            sa.text(
                "INSERT INTO rol_permiso (rol_id, permiso_id) "
                "SELECT r.id, p.id FROM rol r JOIN permiso p ON p.codigo = :codigo "
                "WHERE r.codigo = 'SUPER_ADMIN' AND r.empresa_id IS NULL ON CONFLICT DO NOTHING"
            ).bindparams(codigo=f"platform:{code}")
        )
    op.execute(
        "INSERT INTO rol_permiso (rol_id, permiso_id) "
        "SELECT r.id, p.id FROM rol r JOIN permiso p ON p.codigo = 'platform:nomina:parametros' "
        "WHERE r.codigo = 'SUPER_ADMIN' AND r.empresa_id IS NULL ON CONFLICT DO NOTHING"
    )


def downgrade() -> None:
    for table in (
        "boleta_detalle",
        "boleta_pago",
        "haber_proporcional",
        "impuesto_empleado",
        "periodo_nomina",
        "regla_salarial",
        "estructura_salarial",
        "autorizacion_horas_extra",
        "solicitud_correccion_asistencia",
        "asistencia",
        "solicitud_ausencia",
        "saldo_vacacion",
        "tipo_ausencia",
        "documento_empleado",
        "contrato",
    ):
        op.drop_table(table)
    for code in (*PERMISOS, *(f"platform:{item}" for item in PERMISOS)):
        op.execute(sa.text("DELETE FROM permiso WHERE codigo = :codigo").bindparams(codigo=code))
    op.execute("DELETE FROM permiso WHERE codigo = 'platform:nomina:parametros'")
