from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from ssas.core.security.dependencies import CurrentUser
from ssas.personal.infrastructure.http.notifications_router import (
    mark_all_read,
    mark_read,
    my_notifications,
    router,
)


def _session(*, due=(), notifications=(), item=None):
    session = MagicMock()
    due_result = MagicMock()
    due_result.all.return_value = list(due)
    session.execute = AsyncMock(return_value=due_result)
    session.scalars = AsyncMock(return_value=list(notifications))
    session.scalar = AsyncMock(return_value=item)
    return session


def test_notification_routes_require_authentication():
    assert {route.path for route in router.routes} >= {
        "/notificaciones/mi", "/notificaciones/{notification_id}/leer",
        "/notificaciones/leer-todas", "/notificaciones/dispositivos",
    }


@pytest.mark.asyncio
async def test_inbox_is_scoped_to_current_user_and_company():
    now = datetime.now(UTC)
    item = SimpleNamespace(id="notice-1", tipo="BOLETA_DISPONIBLE", titulo="Boleta",
                           mensaje="Disponible", ruta="/cuenta/mis-boletas", fecha=now, leida_en=None)
    session = _session(notifications=[item])
    result = await my_notifications(user=CurrentUser(id="user-1", empresa_id="company-1"), session=session)
    assert result[0]["tipo"] == "BOLETA_DISPONIBLE"
    sql = str(session.scalars.call_args.args[0].compile())
    assert "notificacion.empresa_id" in sql and "notificacion.usuario_id" in sql


@pytest.mark.asyncio
async def test_cannot_read_another_users_notification():
    session = _session(item=None)
    with pytest.raises(HTTPException) as exc:
        await mark_read(UUID("11111111-1111-1111-1111-111111111111"),
                        user=CurrentUser(id="user-1", empresa_id="company-1"), session=session)
    assert exc.value.status_code == 404
    sql = str(session.scalar.call_args.args[0].compile())
    assert "notificacion.usuario_id" in sql and "notificacion.empresa_id" in sql


@pytest.mark.asyncio
async def test_mark_all_only_updates_own_unread_items():
    session = _session()
    session.execute.return_value.rowcount = 2
    result = await mark_all_read(user=CurrentUser(id="user-1", empresa_id="company-1"), session=session)
    assert result == {"actualizadas": 2}
    sql = str(session.execute.call_args.args[0].compile())
    assert "notificacion.usuario_id" in sql and "notificacion.empresa_id" in sql


@pytest.mark.asyncio
async def test_platform_without_company_has_no_inbox():
    session = _session()
    assert await my_notifications(user=CurrentUser(id="platform", empresa_id=None), session=session) == []
    session.execute.assert_not_awaited()
