from ssas.roles.domain.exceptions import ProtectedRoleError, RoleNotFoundError


class DeleteRole:
    def __init__(self, repository):
        self.repository = repository

    async def execute(self, role_id: str):
        role = await self.repository.get_by_id(role_id)
        if not role:
            raise RoleNotFoundError("Rol no encontrado")
        if role.es_base:
            raise ProtectedRoleError("Los roles base del sistema no se pueden desactivar")
        await self.repository.delete(role_id)
