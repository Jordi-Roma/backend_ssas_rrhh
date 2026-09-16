from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ssas.infrastructure.database.base import Base


class RespaldoModel(Base):
    __tablename__ = "respaldo"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    nombre: Mapped[str] = mapped_column(String(255), nullable=False)
    ruta_storage: Mapped[str | None] = mapped_column(Text)
    formato: Mapped[str] = mapped_column(String(20), nullable=False, default="custom")
    tamano_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    estado: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    creado_por_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="RESTRICT"), nullable=False
    )
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    fecha_finalizacion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fecha_restauracion: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    restaurado_por_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("usuario.id", ondelete="RESTRICT")
    )
    mensaje_error: Mapped[str | None] = mapped_column(Text)
