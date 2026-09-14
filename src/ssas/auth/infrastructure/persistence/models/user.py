from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ssas.infrastructure.database.base import Base
from ssas.roles.infrastructure.persistence.models.role import RoleModel
from ssas.roles.infrastructure.persistence.models.user_role import usuario_rol_table

if TYPE_CHECKING:
    from ssas.auth.infrastructure.persistence.models.password_reset_token import (
        PasswordResetTokenModel,
    )
    from ssas.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
    from ssas.bitacora.infrastructure.persistence.models.audit_log import AuditLogModel
    from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
    from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel


class UserModel(Base):
    __tablename__ = "usuario"
    __table_args__ = (
        UniqueConstraint("empresa_id", "email", name="uq_usuario_empresa_email"),
        UniqueConstraint("empresa_id", "username", name="uq_usuario_empresa_username"),
        Index("idx_usuario_empresa_id", "empresa_id"),
        Index("idx_usuario_email", "email"),
        Index("idx_usuario_bloqueado_hasta", "bloqueado_hasta"),
        Index("idx_usuario_eliminado_at", "eliminado_at"),
        CheckConstraint(
            "intentos_fallidos >= 0",
            name="ck_usuario_intentos_fallidos_no_negativo",
        ),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    # NULL = administrador de la plataforma (no pertenece a ninguna empresa).
    empresa_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("empresa.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column("nombres", String(120), nullable=False)
    apellido: Mapped[str] = mapped_column(
        "apellidos", String(120), nullable=False, server_default=""
    )
    email: Mapped[str] = mapped_column(String(150), nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    hashed_password: Mapped[str] = mapped_column("password_hash", Text, nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    debe_cambiar_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ultimo_intento_fallido: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        "activo", Boolean, nullable=False, server_default="true"
    )
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    eliminado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eliminado_por_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    empresa: Mapped["EmpresaModel | None"] = relationship(back_populates="usuarios")
    roles: Mapped[list["RoleModel"]] = relationship(
        secondary=usuario_rol_table,
        primaryjoin=lambda: UserModel.id == usuario_rol_table.c.usuario_id,
        secondaryjoin=lambda: RoleModel.id == usuario_rol_table.c.rol_id,
        viewonly=True,
    )
    refresh_tokens: Mapped[list["RefreshTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetTokenModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    bitacoras: Mapped[list["AuditLogModel"]] = relationship(back_populates="user")
    vacantes_responsables: Mapped[list["VacanteModel"]] = relationship(back_populates="responsable")


Index(
    "uq_usuario_empresa_email_ci",
    UserModel.empresa_id,
    func.lower(UserModel.email),
    unique=True,
)
Index(
    "uq_usuario_empresa_username_ci",
    UserModel.empresa_id,
    func.lower(UserModel.username),
    unique=True,
)

# PostgreSQL considera que dos NULL son distintos, así que los índices de arriba NO
# impiden dos administradores de plataforma con el mismo correo. Estos índices parciales
# cubren ese caso.
Index(
    "uq_usuario_plataforma_email_ci",
    func.lower(UserModel.email),
    unique=True,
    postgresql_where=UserModel.empresa_id.is_(None),
)
Index(
    "uq_usuario_plataforma_username_ci",
    func.lower(UserModel.username),
    unique=True,
    postgresql_where=UserModel.empresa_id.is_(None),
)
