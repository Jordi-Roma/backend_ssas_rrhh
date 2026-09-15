from types import SimpleNamespace

import pytest

from ssas.usuarios.application.use_cases.actualizar_usuario import ActualizarUsuario
from ssas.usuarios.domain.exceptions import LastAdminCannotBeDisabledError

pytestmark = pytest.mark.asyncio


class FakeUsers:
    def __init__(self, *, selected_roles_keep_admin: bool, active_admins: int = 1):
        self.user = SimpleNamespace(id="admin-1", is_active=True)
        self.selected_roles_keep_admin = selected_roles_keep_admin
        self.active_admins = active_admins
        self.updated = False

    async def get_by_id(self, _user_id, _empresa_id):
        return self.user

    async def role_ids_belong_to_empresa(self, _role_ids, _empresa_id):
        return True

    async def user_has_admin_role(self, _user_id, _empresa_id):
        return True

    async def role_ids_include_admin(self, _role_ids, _empresa_id):
        return self.selected_roles_keep_admin

    async def count_active_admins(self, _empresa_id):
        return self.active_admins

    async def update_usuario(self, **_kwargs):
        self.updated = True
        return self.user


async def test_cannot_remove_admin_role_from_last_active_admin() -> None:
    repository = FakeUsers(selected_roles_keep_admin=False)

    with pytest.raises(LastAdminCannotBeDisabledError):
        await ActualizarUsuario(repository).execute(
            user_id="admin-1",
            empresa_id="empresa-a",
            values={},
            role_ids=["role-recruiter"],
        )

    assert repository.updated is False


async def test_admin_role_can_be_replaced_when_another_admin_exists() -> None:
    repository = FakeUsers(selected_roles_keep_admin=False, active_admins=2)

    await ActualizarUsuario(repository).execute(
        user_id="admin-1",
        empresa_id="empresa-a",
        values={},
        role_ids=["role-recruiter"],
    )

    assert repository.updated is True
