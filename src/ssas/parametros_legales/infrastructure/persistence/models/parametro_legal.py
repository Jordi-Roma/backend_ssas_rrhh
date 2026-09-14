from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ssas.infrastructure.database.base import Base


class ParametroLegalModel(Base):
    """Catalogo global de parametros legales definido por el modelo Sprint 1."""

    __tablename__ = "parametro_legal"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    codigo: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    tipo_valor: Mapped[str] = mapped_column(String(30), nullable=False)
    pais: Mapped[str] = mapped_column(String(80), nullable=False)

    valores: Mapped[list[ParametroValorModel]] = relationship(
        back_populates="parametro", cascade="all, delete-orphan"
    )


class ParametroValorModel(Base):
    """Valores historicos de un parametro y su periodo de vigencia."""

    __tablename__ = "parametro_valor"
    __table_args__ = (
        Index("idx_parametro_valor_parametro_vigencia", "parametro_id", "vigente_desde"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    parametro_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("parametro_legal.id", ondelete="CASCADE"), nullable=False
    )
    valor: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    vigente_desde: Mapped[date] = mapped_column(Date, nullable=False)
    vigente_hasta: Mapped[date] = mapped_column(Date, nullable=False)
    norma_legal: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parametro: Mapped[ParametroLegalModel] = relationship(back_populates="valores")
