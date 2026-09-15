from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class ReporteDefinicionModel(Base):
    __tablename__ = "reporte_definicion"
    __table_args__ = (UniqueConstraint("empresa_id", "nombre", name="uq_reporte_definicion_empresa_nombre"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False, index=True)
    usuario_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    fuente: Mapped[str] = mapped_column(String(60), nullable=False)
    columnas: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    filtros: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    orden: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fecha_registro: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_actualizacion: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class ReporteEjecucionModel(Base):
    __tablename__ = "reporte_ejecucion"
    __table_args__ = (Index("idx_reporte_ejecucion_empresa_fecha", "empresa_id", "fecha_inicio"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False)
    reporte_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), ForeignKey("reporte_definicion.id", ondelete="SET NULL"))
    usuario_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False)
    formato: Mapped[str] = mapped_column(String(20), nullable=False)
    filtros_aplicados: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    cantidad_registros: Mapped[int | None] = mapped_column(Integer)
    fecha_inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
