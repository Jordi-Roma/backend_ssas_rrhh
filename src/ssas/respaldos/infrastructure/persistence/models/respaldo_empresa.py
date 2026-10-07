from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class RespaldoEmpresaModel(Base):
    __tablename__ = "respaldo_empresa"
    __table_args__ = (
        Index("idx_respaldo_empresa_fecha", "empresa_id", "fecha_creacion"),
        Index("idx_respaldo_empresa_estado", "estado"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    empresa_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="RESTRICT"), nullable=False
    )
    origen: Mapped[str] = mapped_column(String(10), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False)
    creado_por_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="SET NULL")
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    fecha_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_finalizacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intentos: Mapped[int] = mapped_column(nullable=False, default=0)
    ruta_storage: Mapped[str | None] = mapped_column(Text)
    tamano_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    version_formato: Mapped[int] = mapped_column(nullable=False, default=1)
    mensaje_error: Mapped[str | None] = mapped_column(Text)
