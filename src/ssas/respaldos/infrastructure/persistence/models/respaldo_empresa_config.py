from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class RespaldoEmpresaConfigModel(Base):
    __tablename__ = "respaldo_empresa_config"

    empresa_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), primary_key=True
    )
    auto_habilitado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hora_local: Mapped[str] = mapped_column(String(5), nullable=False, default="02:00")
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
