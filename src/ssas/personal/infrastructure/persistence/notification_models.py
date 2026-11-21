from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class NotificacionModel(Base):
    __tablename__ = "notificacion"
    __table_args__ = (
        UniqueConstraint("empresa_id", "usuario_id", "evento_clave", name="uq_notificacion_evento_usuario"),
        Index("ix_notificacion_bandeja", "empresa_id", "usuario_id", "fecha"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False)
    usuario_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False)
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    titulo: Mapped[str] = mapped_column(String(160), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    ruta: Mapped[str | None] = mapped_column(String(255))
    evento_clave: Mapped[str] = mapped_column(String(160), nullable=False)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    leida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificacionDispositivoModel(Base):
    __tablename__ = "notificacion_dispositivo"
    __table_args__ = (Index("ix_notificacion_dispositivo_usuario", "empresa_id", "usuario_id"),)

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    empresa_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=False)
    usuario_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
