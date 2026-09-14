from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ssas.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ssas.auth.infrastructure.persistence.models.user import UserModel
    from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel


class AuditLogModel(Base):
    __tablename__ = "bitacora"
    __table_args__ = (
        Index("idx_bitacora_empresa_id", "empresa_id"),
        Index("idx_bitacora_usuario_id", "usuario_id"),
        Index("idx_bitacora_modulo", "modulo"),
        Index("idx_bitacora_accion", "accion"),
        Index("idx_bitacora_fecha", "fecha"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    # NULL = evento de la plataforma (reemplaza a la antigua tabla bitacora_plataforma).
    empresa_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=True
    )
    user_id: Mapped[str | None] = mapped_column(
        "usuario_id",
        UUID(as_uuid=False),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_label: Mapped[str | None] = mapped_column("actor_etiqueta", String(150), nullable=True)
    module: Mapped[str] = mapped_column("modulo", String(80), nullable=False)
    action: Mapped[str] = mapped_column("accion", String(100), nullable=False)
    level: Mapped[str] = mapped_column("nivel", String(16), nullable=False, server_default="INFO")
    description: Mapped[str] = mapped_column("descripcion", Text, nullable=False)
    tabla_afectada: Mapped[str | None] = mapped_column(String(100), nullable=True)
    registro_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    datos_previos_jsonb: Mapped[dict[str, Any] | None] = mapped_column(
        "datos_previos", JSONB, nullable=True
    )
    datos_nuevos_jsonb: Mapped[dict[str, Any] | None] = mapped_column(
        "datos_nuevos", JSONB, nullable=True
    )
    ip_origen: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    fecha: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    empresa: Mapped["EmpresaModel | None"] = relationship(back_populates="bitacoras")
    user: Mapped["UserModel | None"] = relationship(back_populates="bitacoras")
