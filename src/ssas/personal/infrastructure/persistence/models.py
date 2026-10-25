from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


def uuid_pk():
    return mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=text("gen_random_uuid()")
    )


def tenant_fk():
    return mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=False
    )


def employee_fk():
    return mapped_column(
        UUID(as_uuid=False), ForeignKey("empleado.id", ondelete="RESTRICT"), nullable=False
    )


class ContratoModel(Base):
    __tablename__ = "contrato"
    __table_args__ = (
        UniqueConstraint("empresa_id", "numero_contrato", name="uq_contrato_numero_empresa"),
        CheckConstraint("salario_basico > 0", name="ck_contrato_salario"),
        CheckConstraint(
            "fecha_fin IS NULL OR fecha_fin >= fecha_inicio", name="ck_contrato_fechas"
        ),
        Index("idx_contrato_empleado_fecha", "empresa_id", "empleado_id", "fecha_inicio"),
        Index(
            "uq_contrato_vigente_empleado",
            "empleado_id",
            unique=True,
            postgresql_where=text("estado = 'VIGENTE'"),
        ),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    cargo_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("cargo.id", ondelete="RESTRICT"), nullable=False
    )
    departamento_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("departamento.id", ondelete="RESTRICT"), nullable=False
    )
    jefe_directo_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empleado.id", ondelete="RESTRICT")
    )
    contrato_anterior_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("contrato.id", ondelete="RESTRICT")
    )
    numero_contrato: Mapped[str] = mapped_column(String(80), nullable=False)
    tipo_contrato: Mapped[str] = mapped_column(String(30), nullable=False)
    modalidad: Mapped[str] = mapped_column(String(30), nullable=False)
    jornada: Mapped[str] = mapped_column(String(30), nullable=False)
    hora_entrada_programada: Mapped[time] = mapped_column(Time, nullable=False)
    horas_jornada: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    minutos_descanso: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    salario_basico: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, server_default="BOB")
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date | None] = mapped_column(Date)
    motivo_cambio: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="VIGENTE")
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentoEmpleadoModel(Base):
    __tablename__ = "documento_empleado"
    __table_args__ = (Index("idx_documento_empleado", "empresa_id", "empleado_id"),)

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    nombre: Mapped[str] = mapped_column(String(200), nullable=False)
    ruta_privada: Mapped[str] = mapped_column(Text, nullable=False)
    tipo_mime: Mapped[str] = mapped_column(String(100), nullable=False)
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_emision: Mapped[date | None] = mapped_column(Date)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)
    fecha_carga: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TipoAusenciaModel(Base):
    __tablename__ = "tipo_ausencia"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo", name="uq_tipo_ausencia_codigo"),)

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    codigo: Mapped[str] = mapped_column(String(40), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    es_remunerado: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    descuenta_vacacion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    dias_maximos_anio: Mapped[int | None] = mapped_column(Integer)
    requiere_aprobacion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    requiere_documento: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class SaldoVacacionModel(Base):
    __tablename__ = "saldo_vacacion"
    __table_args__ = (
        UniqueConstraint("empresa_id", "empleado_id", "gestion", name="uq_saldo_vacacion_gestion"),
        CheckConstraint(
            "dias_asignados >= 0 AND dias_usados >= 0 AND dias_usados <= dias_asignados",
            name="ck_saldo_vacacion_no_negativo",
        ),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    gestion: Mapped[int] = mapped_column(Integer, nullable=False)
    dias_asignados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    dias_usados: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class SolicitudAusenciaModel(Base):
    __tablename__ = "solicitud_ausencia"
    __table_args__ = (
        CheckConstraint(
            "fecha_fin >= fecha_inicio AND dias_solicitados > 0",
            name="ck_solicitud_ausencia_fechas",
        ),
        CheckConstraint(
            "dias_descontados IS NULL OR (dias_descontados > 0 AND dias_descontados <= dias_solicitados)",
            name="ck_solicitud_ausencia_descuento",
        ),
        Index("idx_solicitud_ausencia_empresa_estado", "empresa_id", "estado"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    tipo_ausencia_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("tipo_ausencia.id", ondelete="RESTRICT"), nullable=False
    )
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    fecha_fin: Mapped[date] = mapped_column(Date, nullable=False)
    dias_solicitados: Mapped[int] = mapped_column(Integer, nullable=False)
    dias_descontados: Mapped[int | None] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    documento_url: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDIENTE")
    observacion_jefe: Mapped[str | None] = mapped_column(Text)
    resuelto_por_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL")
    )
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AsistenciaModel(Base):
    __tablename__ = "asistencia"
    __table_args__ = (
        UniqueConstraint("empresa_id", "empleado_id", "fecha", name="uq_asistencia_empleado_fecha"),
        CheckConstraint(
            "horas_trabajadas >= 0 AND horas_extra >= 0 AND minutos_retraso >= 0",
            name="ck_asistencia_tiempos",
        ),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora_entrada: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hora_salida: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lat_entrada: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lon_entrada: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lat_salida: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lon_salida: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    horas_trabajadas: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), nullable=False, server_default="0"
    )
    horas_extra: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, server_default="0")
    minutos_retraso: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    origen: Mapped[str] = mapped_column(String(20), nullable=False)


class SolicitudCorreccionAsistenciaModel(Base):
    __tablename__ = "solicitud_correccion_asistencia"
    __table_args__ = (
        Index(
            "uq_correccion_asistencia_pendiente",
            "empresa_id",
            "empleado_id",
            "fecha",
            unique=True,
            postgresql_where=text("estado = 'PENDIENTE'"),
        ),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    asistencia_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("asistencia.id", ondelete="RESTRICT")
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    nueva_entrada: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nueva_salida: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="PENDIENTE")
    observacion_jefe: Mapped[str | None] = mapped_column(Text)
    resuelto_por_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL")
    )
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AutorizacionHorasExtraModel(Base):
    __tablename__ = "autorizacion_horas_extra"
    __table_args__ = (
        UniqueConstraint("asistencia_id", name="uq_autorizacion_extra_asistencia"),
        CheckConstraint(
            "horas_solicitadas > 0 AND (monto_autorizado IS NULL OR monto_autorizado > 0)",
            name="ck_autorizacion_extra_positiva",
        ),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    empleado_id: Mapped[str] = employee_fk()
    asistencia_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("asistencia.id", ondelete="RESTRICT"), nullable=False
    )
    horas_solicitadas: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    motivo: Mapped[str] = mapped_column(Text, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="JEFE_PENDIENTE")
    jefe_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL")
    )
    jefe_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rrhh_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL")
    )
    rrhh_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    monto_autorizado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    referencia_calculo: Mapped[str | None] = mapped_column(String(160))
    observacion: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EstructuraSalarialModel(Base):
    __tablename__ = "estructura_salarial"
    __table_args__ = (
        UniqueConstraint("empresa_id", "nombre", name="uq_estructura_salarial_nombre"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class ReglaSalarialModel(Base):
    __tablename__ = "regla_salarial"
    __table_args__ = (
        UniqueConstraint("estructura_id", "codigo", name="uq_regla_salarial_codigo"),
        UniqueConstraint("estructura_id", "secuencia", name="uq_regla_salarial_secuencia"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    estructura_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("estructura_salarial.id", ondelete="RESTRICT"),
        nullable=False,
    )
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    secuencia: Mapped[int] = mapped_column(Integer, nullable=False)
    tipo_calculo: Mapped[str] = mapped_column(String(20), nullable=False)
    monto_fijo: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    porcentaje: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    base_calculo: Mapped[str | None] = mapped_column(String(40))
    formula: Mapped[str | None] = mapped_column(Text)
    condicion: Mapped[str | None] = mapped_column(String(100))
    parametro_codigo: Mapped[str | None] = mapped_column(String(80))
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class PeriodoNominaModel(Base):
    __tablename__ = "periodo_nomina"
    __table_args__ = (
        UniqueConstraint("empresa_id", "gestion", "mes", name="uq_periodo_nomina_mes"),
        CheckConstraint("mes BETWEEN 1 AND 12", name="ck_periodo_nomina_mes"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    gestion: Mapped[int] = mapped_column(Integer, nullable=False)
    mes: Mapped[int] = mapped_column(Integer, nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ABIERTO")
    calculado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprobado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprobado_por_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL")
    )


class ImpuestoEmpleadoModel(Base):
    __tablename__ = "impuesto_empleado"
    __table_args__ = (
        UniqueConstraint("periodo_id", "empleado_id", name="uq_impuesto_empleado_periodo"),
        CheckConstraint("rc_iva_retenido >= 0", name="ck_impuesto_empleado_no_negativo"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    periodo_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("periodo_nomina.id", ondelete="RESTRICT"), nullable=False
    )
    empleado_id: Mapped[str] = employee_fk()
    rc_iva_retenido: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    datos_tributarios: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    referencia_planilla: Mapped[str] = mapped_column(String(160), nullable=False)
    registrado_por_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False
    )
    registrado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HaberProporcionalModel(Base):
    __tablename__ = "haber_proporcional"
    __table_args__ = (
        UniqueConstraint("periodo_id", "empleado_id", name="uq_haber_proporcional_periodo"),
        CheckConstraint("dias_pagados BETWEEN 1 AND 31", name="ck_haber_proporcional_dias"),
        CheckConstraint("haber_basico_pagado > 0", name="ck_haber_proporcional_monto"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    periodo_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("periodo_nomina.id", ondelete="RESTRICT"), nullable=False
    )
    empleado_id: Mapped[str] = employee_fk()
    dias_pagados: Mapped[int] = mapped_column(Integer, nullable=False)
    haber_basico_pagado: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    referencia_calculo: Mapped[str] = mapped_column(String(160), nullable=False)
    registrado_por_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False
    )
    registrado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoletaPagoModel(Base):
    __tablename__ = "boleta_pago"
    __table_args__ = (
        UniqueConstraint("periodo_id", "empleado_id", name="uq_boleta_periodo_empleado"),
    )

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    periodo_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("periodo_nomina.id", ondelete="RESTRICT"), nullable=False
    )
    empleado_id: Mapped[str] = employee_fk()
    contrato_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("contrato.id", ondelete="RESTRICT"), nullable=False
    )
    dias_trabajados: Mapped[int] = mapped_column(Integer, nullable=False)
    salario_basico: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_ganado: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_descuentos: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    liquido_pagable: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_aportes_patronales: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)


class BoletaDetalleModel(Base):
    __tablename__ = "boleta_detalle"
    __table_args__ = (Index("idx_boleta_detalle_boleta", "boleta_id"),)

    id: Mapped[str] = uuid_pk()
    empresa_id: Mapped[str] = tenant_fk()
    boleta_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("boleta_pago.id", ondelete="CASCADE"), nullable=False
    )
    regla_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("regla_salarial.id", ondelete="SET NULL")
    )
    codigo: Mapped[str] = mapped_column(String(60), nullable=False)
    nombre: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    cantidad: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="1")
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
