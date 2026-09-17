from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ssas.infrastructure.database.base import Base

if TYPE_CHECKING:
    from ssas.auth.infrastructure.persistence.models.password_reset_token import (
        PasswordResetTokenModel,
    )
    from ssas.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
    from ssas.auth.infrastructure.persistence.models.user import UserModel
    from ssas.bitacora.infrastructure.persistence.models.audit_log import AuditLogModel
    from ssas.cargos.infrastructure.persistence.models.cargo import CargoModel
    from ssas.departamentos.infrastructure.persistence.models.departamento import (
        DepartamentoModel,
    )
    from ssas.empresas.infrastructure.persistence.models.suscripcion import SuscripcionModel
    from ssas.habilidades.infrastructure.persistence.models.habilidad import HabilidadModel
    from ssas.postulaciones.infrastructure.persistence.models.etapa_reclutamiento import (
        EtapaReclutamientoModel,
    )
    from ssas.postulaciones.infrastructure.persistence.models.motivo_rechazo import (
        MotivoRechazoModel,
    )
    from ssas.postulantes.infrastructure.persistence.models.postulante import PostulanteModel
    from ssas.roles.infrastructure.persistence.models.role import RoleModel
    from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel


class EmpresaModel(Base):
    __tablename__ = "empresa"
    __table_args__ = (
        CheckConstraint("length(trim(slug)) > 0", name="chk_empresa_slug_no_vacio"),
        Index("idx_empresa_eliminado_at", "eliminado_at"),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    nit: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    razon_social: Mapped[str] = mapped_column(String(200), nullable=False)
    nombre_comercial: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)
    direccion: Mapped[str | None] = mapped_column(Text, nullable=True)
    ciudad: Mapped[str | None] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    color_primario: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="#2563eb"
    )
    portal_publico_activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    eliminado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    eliminado_por_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)
    fecha_registro: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    usuarios: Mapped[list["UserModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    roles: Mapped[list["RoleModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshTokenModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[list["PasswordResetTokenModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    bitacoras: Mapped[list["AuditLogModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    departamentos: Mapped[list["DepartamentoModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    cargos: Mapped[list["CargoModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    habilidades: Mapped[list["HabilidadModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    vacantes: Mapped[list["VacanteModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    etapas_reclutamiento: Mapped[list["EtapaReclutamientoModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    motivos_rechazo: Mapped[list["MotivoRechazoModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    postulantes: Mapped[list["PostulanteModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )
    suscripciones: Mapped[list["SuscripcionModel"]] = relationship(
        back_populates="empresa", cascade="all, delete-orphan"
    )


Index("uq_empresa_slug_ci", func.lower(EmpresaModel.slug), unique=True)
#creacion de rama remota para el backend
