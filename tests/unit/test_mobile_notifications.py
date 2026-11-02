from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ssas.core.security.dependencies import CurrentUser
from ssas.personal.infrastructure.http.notifications_router import my_notifications, router


def _session(*, worker_id=None, decisions=(), pending=(), events=()):
    session = MagicMock()
    session.scalar = AsyncMock(return_value=worker_id)
    results = []
    for rows in (decisions, pending, events):
        result = MagicMock()
        result.all.return_value = list(rows)
        results.append(result)
    session.execute = AsyncMock(return_value=results[0])
    session.scalars = AsyncMock(side_effect=results[1:])
    return session


def test_notification_route_requires_authenticated_user():
    assert [route.path for route in router.routes] == ["/notificaciones/mi"]


@pytest.mark.asyncio
async def test_absence_decision_only_uses_own_employee_and_tenant():
    moment = datetime.now(UTC)
    request = SimpleNamespace(id="request-1", estado="APROBADA", resuelto_en=moment)
    session = _session(worker_id="employee-1", decisions=[(request, "Vacación")])
    user = CurrentUser(id="user-1", empresa_id="company-1", roles=["EMPLEADO"])
    result = await my_notifications(user=user, session=session)
    assert result[0]["tipo"] == "AUSENCIA_RESUELTA"
    sql = str(session.execute.call_args.args[0].compile())
    assert "solicitud_ausencia.empresa_id" in sql
    assert "solicitud_ausencia.empleado_id" in sql
    session.scalars.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_events_are_only_shown_to_company_admin():
    moment = datetime.now(UTC)
    event = SimpleNamespace(id="event-1", fecha=moment, datos_nuevos_jsonb={"estado": "ACTIVA"})
    session = _session(events=[event])
    user = CurrentUser(id="admin-1", empresa_id="company-1", roles=["ADMIN_EMPRESA"])
    result = await my_notifications(user=user, session=session)
    assert result[0]["tipo"] == "SUSCRIPCION"
    sql = str(session.scalars.call_args.args[0].compile())
    assert "bitacora.empresa_id" in sql


@pytest.mark.asyncio
async def test_platform_user_gets_no_company_notifications():
    session = _session()
    result = await my_notifications(user=CurrentUser(id="platform", empresa_id=None), session=session)
    assert result == []
    session.scalar.assert_not_awaited()
