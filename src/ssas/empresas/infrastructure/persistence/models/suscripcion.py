from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, func
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
    modulos: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

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

    empresa = relationship("EmpresaModel", back_populates="suscripciones")
    plan: Mapped[PlanSuscripcionModel] = relationship(back_populates="suscripciones")
