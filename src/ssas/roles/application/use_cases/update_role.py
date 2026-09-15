from ssas.roles.domain.exceptions import DuplicateRoleError, ProtectedRoleError, RoleNotFoundError


class UpdateRole:
    def __init__(self, repository):
        self.repository = repository

    async def execute(self, role_id: str, values: dict):
        role = await self.repository.get_by_id(role_id)
        if not role:
            raise RoleNotFoundError("Rol no encontrado")
        if role.es_base:
            raise ProtectedRoleError("Los roles base del sistema no se pueden modificar")
        normalized_values = dict(values)
        name = normalized_values.get("name")
        if isinstance(name, str):
            name = name.strip()
            normalized_values["name"] = name
        if name and name != role.name and await self.repository.get_by_name(name):
            raise DuplicateRoleError("El rol ya existe")
        description = normalized_values.get("description")
        if isinstance(description, str):
            normalized_values["description"] = description.strip() or None
        return await self.repository.update(role_id, normalized_values)
