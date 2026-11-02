from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ssas.core.security import dependencies
from ssas.roles.domain.exceptions import PermissionDeniedError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "granted"),
    [
        (False, "boletas:ver"),
        (False, "boletas:mi"),
        (False, "nomina:gestionar"),
        (True, "platform:boletas:ver"),
    ],
)
async def test_period_list_accepts_each_authorized_reader(monkeypatch, platform, granted):
    checked = []

    class Authorization:
        def __init__(self, _repository):
            pass

        async def execute(self, *, required_permission, **_kwargs):
            checked.append(required_permission)
            if required_permission != granted:
                raise PermissionDeniedError("Sin permiso")

    monkeypatch.setattr(dependencies, "CheckPermission", Authorization)
    monkeypatch.setattr(dependencies, "SqlAlchemyAuthorizationRepository", lambda session: session)
    user = dependencies.CurrentUser(id="user-1", empresa_id=None if platform else "company-1")
    reader = dependencies.require_scoped_any_permission(
        ("nomina:ver", "nomina:gestionar", "boletas:ver", "boletas:mi"),
        ("platform:nomina:ver", "platform:nomina:gestionar", "platform:boletas:ver"),
    )
    assert await reader(current_user=user, session=SimpleNamespace()) is user
    assert granted in checked


@pytest.mark.asyncio
async def test_period_list_rejects_unrelated_permissions(monkeypatch):
    class Authorization:
        def __init__(self, _repository):
            pass

        async def execute(self, **_kwargs):
            raise PermissionDeniedError("Sin permiso")

    monkeypatch.setattr(dependencies, "CheckPermission", Authorization)
    monkeypatch.setattr(dependencies, "SqlAlchemyAuthorizationRepository", lambda session: session)
    reader = dependencies.require_scoped_any_permission(("boletas:ver",), ("platform:boletas:ver",))
    with pytest.raises(HTTPException) as error:
        await reader(current_user=dependencies.CurrentUser(id="user-1", empresa_id="company-1"), session=SimpleNamespace())
    assert error.value.status_code == 403
