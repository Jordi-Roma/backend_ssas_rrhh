"""Audit trail for sensitive Sprint 3 operations."""

from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.security.dependencies import CurrentUser


async def record_personal_event(
    session: AsyncSession,
    user: CurrentUser,
    company: str | None,
    *,
    action: str,
    table: str,
    record_id: str,
    data: dict | None = None,
) -> None:
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=company,
        module="PERSONAL",
        action=action,
        description=action.replace("_", " ").capitalize(),
        user_id=user.id,
        affected_table=table,
        record_id=record_id,
        new_data=data,
    )
