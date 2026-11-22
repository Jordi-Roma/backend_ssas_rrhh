from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class MovimientoFinancieroModel(Base):
    __tablename__ = "movimiento_financiero"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    empresa_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="SET NULL"))
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)
    categoria: Mapped[str] = mapped_column(String(120), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    moneda: Mapped[str] = mapped_column(String(3), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    fuente: Mapped[str] = mapped_column(String(30), nullable=False)
    referencia: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    descripcion: Mapped[str | None] = mapped_column(Text)
    entorno_prueba: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
