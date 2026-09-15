from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.infrastructure.persistence.models.email_verification_token import (
    EmailVerificationTokenModel,
)
from ssas.auth.infrastructure.persistence.models.password_reset_token import PasswordResetTokenModel
from ssas.auth.infrastructure.persistence.models.refresh_token import RefreshTokenModel
from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.domain.entities.audit_log import AuditLog
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel


class PlatformRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_empresas(
        self,
        search: str | None,
        activo: bool | None,
        page: int,
        per_page: int,
        include_deleted: bool = False,
    ) -> tuple[list[EmpresaModel], int]:
        filters = [] if include_deleted else [EmpresaModel.eliminado_at.is_(None)]
        if activo is not None:
            filters.append(EmpresaModel.activo.is_(activo))
        if search:
            term = f"%{search.strip().lower()}%"
            filters.append(
                or_(
                    func.lower(EmpresaModel.razon_social).like(term),
                    func.lower(EmpresaModel.nombre_comercial).like(term),
                    func.lower(EmpresaModel.slug).like(term),
                    func.lower(func.coalesce(EmpresaModel.nit, "")).like(term),
                )
            )
        total = (
            await self.session.execute(select(func.count(EmpresaModel.id)).where(*filters))
        ).scalar_one()
        query = (
            select(EmpresaModel)
            .where(*filters)
            .order_by(EmpresaModel.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return list((await self.session.execute(query)).scalars().unique().all()), total

    async def get_empresa(
        self, empresa_id: str, *, lock: bool = False, include_deleted: bool = False
    ) -> EmpresaModel | None:
        query = select(EmpresaModel).where(EmpresaModel.id == empresa_id)
        if not include_deleted:
            query = query.where(EmpresaModel.eliminado_at.is_(None))
        if lock:
            query = query.with_for_update()
        return (await self.session.execute(query)).scalar_one_or_none()

    async def get_empresa_by_unique(self, nit: str | None, slug: str) -> EmpresaModel | None:
        conditions = [func.lower(EmpresaModel.slug) == slug.strip().lower()]
        if nit:
            conditions.append(EmpresaModel.nit == nit.strip())
        return (
            await self.session.execute(select(EmpresaModel).where(or_(*conditions)))
        ).scalar_one_or_none()

    async def update_empresa(self, empresa_id: str, values: dict) -> EmpresaModel | None:
        await self.session.execute(
            update(EmpresaModel).where(EmpresaModel.id == empresa_id).values(**values)
        )
        await self.session.flush()
        return await self.get_empresa(empresa_id)

    async def soft_delete_empresa(self, empresa_id: str, actor_id: str) -> EmpresaModel:
        now = datetime.now(UTC)
        await self.session.execute(
            update(EmpresaModel)
            .where(EmpresaModel.id == empresa_id, EmpresaModel.eliminado_at.is_(None))
            .values(activo=False, eliminado_at=now, eliminado_por_id=actor_id)
        )
        await self.session.execute(
            update(UserModel)
            .where(UserModel.empresa_id == empresa_id)
            .values(is_active=False)
        )
        await self.session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.empresa_id == empresa_id,
                RefreshTokenModel.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.session.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.empresa_id == empresa_id,
                PasswordResetTokenModel.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.session.execute(
            update(EmailVerificationTokenModel)
            .where(
                EmailVerificationTokenModel.empresa_id == empresa_id,
                EmailVerificationTokenModel.used_at.is_(None),
            )
            .values(used_at=now)
        )
        await self.session.flush()
        empresa = await self.get_empresa(empresa_id, include_deleted=True)
        assert empresa is not None
        return empresa

    async def restore_empresa(self, empresa_id: str) -> EmpresaModel:
        await self.session.execute(
            update(EmpresaModel)
            .where(EmpresaModel.id == empresa_id, EmpresaModel.eliminado_at.is_not(None))
            .values(activo=False, eliminado_at=None, eliminado_por_id=None)
        )
        await self.session.flush()
        empresa = await self.get_empresa(empresa_id)
        assert empresa is not None
        return empresa

    # ── Bitácora ──────────────────────────────────────────────────────────────
    # Los eventos de plataforma son filas de 'bitacora' con empresa_id NULL. Antes
    # vivían en una tabla aparte, 'bitacora_plataforma', duplicando el modelo entero.

    async def add_audit(
        self,
        admin_id: str | None = None,
        actor_etiqueta: str | None = None,
        modulo: str = "PLATFORM",
        accion: str = "INFO",
        nivel: str = "INFO",
        descripcion: str = "",
        tabla_afectada: str | None = None,
        registro_id: str | None = None,
        datos_previos: dict | None = None,
        datos_nuevos: dict | None = None,
        ip_origen: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        del nivel  # El nivel se deriva de la acción en el caso de uso central.
        return await RegisterAuditEvent(SqlAlchemyAuditLogRepository(self.session)).execute(
            empresa_id=None,
            user_id=admin_id,
            actor_label=actor_etiqueta,
            module=modulo,
            action=accion,
            description=descripcion,
            affected_table=tabla_afectada,
            record_id=registro_id,
            previous_data=datos_previos,
            new_data=datos_nuevos,
            source_ip=ip_origen,
            user_agent=user_agent,
        )
