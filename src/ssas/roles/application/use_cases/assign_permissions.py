from ssas.roles.domain.exceptions import (
    PermissionNotFoundError,
    ProtectedRoleError,
    RoleNotFoundError,
)

PREFIJO_PLATAFORMA = "platform:"


class AssignPermissions:
    def __init__(self, role_repository, permission_repository):
        self.role_repository = role_repository
        self.permission_repository = permission_repository

    async def execute(self, role_id: str, permission_ids: list[str]):
        role = await self.role_repository.get_by_id(role_id)
        if not role:
            raise RoleNotFoundError("Rol no encontrado")
        if role.es_base:
            raise ProtectedRoleError("Los permisos de los roles base no se pueden modificar")

        permissions = await self.permission_repository.get_by_ids(permission_ids)
        if len(permissions) != len(set(permission_ids)):
            raise PermissionNotFoundError("Una o más permisos no existen")

        # Sin esto, el administrador de una empresa podría crear un rol, asignarle
        # 'platform:empresas:crear' y dárselo a sí mismo: escalada de privilegios.
        # Los permisos de plataforma solo pueden vivir en roles globales (empresa_id NULL).
        if getattr(role, "empresa_id", None) is not None:
            de_plataforma = sorted(
                permiso.name
                for permiso in permissions
                if permiso.name.startswith(PREFIJO_PLATAFORMA)
            )
            if de_plataforma:
                raise PermissionNotFoundError(
                    "Un rol de empresa no puede recibir permisos de plataforma: "
                    + ", ".join(de_plataforma)
                )

        return await self.role_repository.assign_permissions(role_id, permissions)
