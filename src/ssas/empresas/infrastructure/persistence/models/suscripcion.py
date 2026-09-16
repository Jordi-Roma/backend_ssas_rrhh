from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ssas.infrastructure.database.base import Base


class PlanSuscripcionModel(Base):
    __tablename__ = "plan_suscripcion"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    nombre: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    precio_mensual: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_empleados: Mapped[int] = mapped_column(Integer, nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False, server_default="USD")
    max_usuarios: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    max_vacantes_activas: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    max_almacenamiento_mb: Mapped[int] = mapped_column(Integer, nullable=False, server_default="250")
    stripe_price_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    modulos: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    suscripciones: Mapped[list[SuscripcionModel]] = relationship(back_populates="plan")


class SuscripcionModel(Base):
    __tablename__ = "suscripcion"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    empresa_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("plan_suscripcion.id", ondelete="RESTRICT"), nullable=False
    )
    fecha_inicio: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    fecha_fin: Mapped[date | None] = mapped_column(Date, nullable=True)
    estado: Mapped[str] = mapped_column(String(30), nullable=False, server_default="ACTIVA")
    periodo_prueba_hasta: Mapped[date | None] = mapped_column(Date)
    cancelar_al_fin_periodo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    stripe_checkout_session_id: Mapped[str | None] = mapped_column(String(120), unique=True)
    fecha_ultimo_pago: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_proximo_cobro: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_por_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    empresa = relationship("EmpresaModel", back_populates="suscripciones")
    plan: Mapped[PlanSuscripcionModel] = relationship(back_populates="suscripciones")
