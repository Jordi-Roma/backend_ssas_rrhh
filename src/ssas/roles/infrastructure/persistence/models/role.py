from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ssas.infrastructure.database.base import Base
from ssas.roles.infrastructure.persistence.models.role_permission import rol_permiso_table

if TYPE_CHECKING:
    from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
    from ssas.roles.infrastructure.persistence.models.permission import PermissionModel


class RoleModel(Base):
    __tablename__ = "rol"
    __table_args__ = (
        UniqueConstraint("empresa_id", "codigo", name="uq_rol_empresa_codigo"),
        UniqueConstraint("empresa_id", "nombre", name="uq_rol_empresa_nombre"),
        Index("idx_rol_empresa_id", "empresa_id"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    # NULL = rol global de la plataforma (p. ej. SUPER_ADMIN).
    empresa_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column("nombre", String(120), nullable=False)
    codigo: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column("descripcion", Text, nullable=True)
    es_base: Mapped[bool] = mapped_column(
        "es_sistema", Boolean, nullable=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        "activo", Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    empresa: Mapped["EmpresaModel | None"] = relationship(back_populates="roles")
    permissions: Mapped[list["PermissionModel"]] = relationship(
        secondary=rol_permiso_table, back_populates="roles"
    )


Index(
    "uq_rol_empresa_codigo_ci",
    RoleModel.empresa_id,
    func.lower(RoleModel.codigo),
    unique=True,
)
Index(
    "uq_rol_empresa_nombre_ci",
    RoleModel.empresa_id,
    func.lower(RoleModel.name),
    unique=True,
)

# Mismo motivo que en usuario: los índices de arriba no alcanzan cuando empresa_id es NULL.
Index(
    "uq_rol_global_codigo_ci",
    func.lower(RoleModel.codigo),
    unique=True,
    postgresql_where=RoleModel.empresa_id.is_(None),
)
Index(
    "uq_rol_global_nombre_ci",
    func.lower(RoleModel.name),
    unique=True,
    postgresql_where=RoleModel.empresa_id.is_(None),
)
