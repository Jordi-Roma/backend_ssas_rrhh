from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.dto.audit_log_filter import AuditLogFilter
from ssas.bitacora.domain.entities.audit_log import AuditLog
from ssas.bitacora.infrastructure.persistence.models.audit_log import AuditLogModel
from ssas.bitacora.ports.outgoing.audit_log_repository import AuditLogRepository


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, audit_log: AuditLog) -> AuditLog:
        self.session.add(
            AuditLogModel(
                id=audit_log.id,
                empresa_id=audit_log.empresa_id,
                user_id=audit_log.user_id,
                actor_label=audit_log.actor_label,
                module=audit_log.module,
                action=audit_log.action,
                level=audit_log.level,
                description=audit_log.description,
                tabla_afectada=audit_log.affected_table,
                registro_id=audit_log.record_id,
                datos_previos_jsonb=audit_log.previous_data,
                datos_nuevos_jsonb=audit_log.new_data,
                ip_origen=audit_log.source_ip,
                user_agent=audit_log.user_agent,
                fecha=audit_log.created_at,
            )
        )
        await self.session.flush()
        return audit_log

    async def list(self, filters: AuditLogFilter) -> tuple[list[AuditLog], int]:
        conditions = self._conditions(filters)
        total_result = await self.session.execute(
            select(func.count(AuditLogModel.id)).where(*conditions)
        )
        result = await self.session.execute(
            select(AuditLogModel)
            .where(*conditions)
            .order_by(AuditLogModel.fecha.desc())
            .offset(filters.offset)
            .limit(filters.per_page)
        )
        return (
            [self._to_entity(model) for model in result.scalars().all()],
            total_result.scalar_one(),
        )

    async def get_by_id(self, audit_log_id: str, empresa_id: str | None) -> AuditLog | None:
        result = await self.session.execute(
            select(AuditLogModel).where(
                AuditLogModel.id == audit_log_id,
                AuditLogModel.empresa_id == empresa_id,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    @staticmethod
    def _conditions(filters: AuditLogFilter) -> list:
        conditions = [AuditLogModel.empresa_id == filters.empresa_id]
        if filters.user_id:
            conditions.append(AuditLogModel.user_id == filters.user_id)
        if filters.module:
            conditions.append(AuditLogModel.module == filters.module)
        if filters.action:
            conditions.append(AuditLogModel.action == filters.action)
        if filters.level:
            conditions.append(AuditLogModel.level == filters.level)
        if filters.affected_table:
            conditions.append(AuditLogModel.tabla_afectada == filters.affected_table)
        if filters.record_id:
            conditions.append(AuditLogModel.registro_id == filters.record_id)
        if filters.start_date:
            conditions.append(AuditLogModel.fecha >= filters.start_date)
        if filters.end_date:
            conditions.append(AuditLogModel.fecha <= filters.end_date)
        return conditions

    @staticmethod
    def _to_entity(model: AuditLogModel) -> AuditLog:
        return AuditLog(
            id=model.id,
            empresa_id=model.empresa_id,
            user_id=model.user_id,
            actor_label=model.actor_label,
            module=model.module,
            action=model.action,
            level=model.level,
            description=model.description,
            affected_table=model.tabla_afectada,
            record_id=model.registro_id,
            previous_data=model.datos_previos_jsonb,
            new_data=model.datos_nuevos_jsonb,
            source_ip=model.ip_origen,
            user_agent=model.user_agent,
            created_at=model.fecha,
        )
