from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.empresas.infrastructure.persistence.models.suscripcion import SuscripcionModel


def derived_status(
    subscription: SuscripcionModel,
    *,
    today: date,
    now: datetime,
    grace_days: int,
) -> str:
    if (
        subscription.estado == "PRUEBA"
        and subscription.periodo_prueba_hasta is not None
        and subscription.periodo_prueba_hasta < today
    ):
        return "VENCIDA"
    if subscription.fecha_fin is not None and subscription.fecha_fin < today:
        return "CANCELADA" if subscription.cancelar_al_fin_periodo else "VENCIDA"
    if (
        subscription.estado == "PAGO_FALLIDO"
        and subscription.updated_at + timedelta(days=grace_days) < now
    ):
        return "SUSPENDIDA"
    return subscription.estado


async def reconcile_subscriptions(session: AsyncSession, grace_days: int) -> int:
    subscriptions = (await session.execute(select(SuscripcionModel))).scalars().all()
    now = datetime.now(UTC)
    today = now.date()
    changed = 0
    audit = RegisterAuditEvent(SqlAlchemyAuditLogRepository(session))

    for subscription in subscriptions:
        new_status = derived_status(
            subscription,
            today=today,
            now=now,
            grace_days=grace_days,
        )
        if new_status == subscription.estado:
            continue
        previous = subscription.estado
        subscription.estado = new_status
        await audit.execute(
            empresa_id=subscription.empresa_id,
            module="SUSCRIPCION",
            action="SUBSCRIPTION_RECONCILED",
            description="Estado de suscripción reconciliado automáticamente",
            affected_table="suscripcion",
            record_id=subscription.id,
            previous_data={"estado": previous},
            new_data={"estado": new_status},
        )
        changed += 1

    return changed
