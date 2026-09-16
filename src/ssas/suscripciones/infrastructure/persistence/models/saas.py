from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class PlanModuloModel(Base):
    __tablename__ = "plan_modulo"
    __table_args__ = (UniqueConstraint("plan_id", "modulo_id", name="uq_plan_modulo"),)

    plan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("plan_suscripcion.id", ondelete="CASCADE"), primary_key=True)
    modulo_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("modulo.id", ondelete="CASCADE"), primary_key=True)


class StripeEventoModel(Base):
    __tablename__ = "stripe_evento"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    stripe_event_id: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    estado_procesamiento: Mapped[str] = mapped_column(String(30), nullable=False)
    fecha_recepcion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_procesamiento: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    error: Mapped[str | None] = mapped_column(Text)
