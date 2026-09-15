from types import SimpleNamespace

import pytest

from ssas.roles.application.use_cases.assign_permissions import AssignPermissions
from ssas.roles.application.use_cases.create_role import CreateRole
from ssas.roles.application.use_cases.delete_role import DeleteRole
from ssas.roles.domain.exceptions import PermissionNotFoundError, ProtectedRoleError

pytestmark = pytest.mark.asyncio


class FakeRoleRepository:
    def __init__(self):
        self.roles = []

    async def get_by_name(self, name):
        return next((role for role in self.roles if role.name == name), None)

    async def get_by_code(self, code):
        return next((role for role in self.roles if role.codigo == code), None)

    async def create(self, role):
        self.roles.append(role)
        return role


async def test_create_role_keeps_company_and_normalizes_code() -> None:
    repository = FakeRoleRepository()

    role = await CreateRole(repository).execute(
        empresa_id="empresa-a",
        name="Reclutador",
        codigo="reclutador",
    )

    assert role.empresa_id == "empresa-a"
    assert role.codigo == "RECLUTADOR"


class FakeManagedRoleRepository:
    def __init__(self, role):
        self.role = role
        self.deleted = False
        self.assigned = None

    async def get_by_id(self, _role_id):
        return self.role

    async def delete(self, _role_id):
        self.deleted = True

    async def assign_permissions(self, _role_id, permissions):
        self.assigned = permissions
        return self.role


class FakePermissions:
    def __init__(self, permissions):
        self.permissions = permissions

    async def get_by_ids(self, _permission_ids):
        return self.permissions


async def test_base_role_cannot_be_deactivated() -> None:
    repository = FakeManagedRoleRepository(SimpleNamespace(es_base=True))

    with pytest.raises(ProtectedRoleError):
        await DeleteRole(repository).execute("role-base")

    assert repository.deleted is False


async def test_company_role_cannot_receive_platform_permission() -> None:
    role = SimpleNamespace(id="role-1", empresa_id="empresa-a", es_base=False)
    repository = FakeManagedRoleRepository(role)
    permissions = FakePermissions(
        [SimpleNamespace(id="permission-1", name="platform:empresas:crear")]
    )

    with pytest.raises(PermissionNotFoundError):
        await AssignPermissions(repository, permissions).execute(
            "role-1", ["permission-1"]
        )

    assert repository.assigned is None


async def test_custom_role_can_be_left_without_permissions() -> None:
    role = SimpleNamespace(id="role-1", empresa_id="empresa-a", es_base=False)
    repository = FakeManagedRoleRepository(role)

    result = await AssignPermissions(repository, FakePermissions([])).execute("role-1", [])

    assert result is role
    assert repository.assigned == []
