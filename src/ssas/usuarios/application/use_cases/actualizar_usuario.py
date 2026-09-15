from ssas.usuarios.domain.entities.usuario import Usuario
from ssas.usuarios.domain.exceptions import (
    InvalidRoleForEmpresaError,
    LastAdminCannotBeDisabledError,
    UsuarioAlreadyExistsError,
    UsuarioNotFoundError,
    UsuarioWithoutRoleError,
)
from ssas.usuarios.ports.outgoing.usuario_repository import UsuarioRepository


class ActualizarUsuario:
    def __init__(self, usuario_repository: UsuarioRepository):
        self.usuario_repository = usuario_repository

    async def execute(
        self,
        user_id: str,
        empresa_id: str | None,
        values: dict,
        role_ids: list[str] | None = None,
    ) -> Usuario:
        usuario = await self.usuario_repository.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")

        updates = dict(values)
        if "email" in updates and updates["email"] is not None:
            normalized_email = updates["email"].strip().lower()
            existing = await self.usuario_repository.get_by_email(normalized_email, empresa_id)
            if existing and existing.id != user_id:
                raise UsuarioAlreadyExistsError("Ya existe un usuario con ese email en la empresa")
            updates["email"] = normalized_email

        if "username" in updates and updates["username"] is not None:
            normalized_username = updates["username"].strip().lower()
            existing = await self.usuario_repository.get_by_username(
                normalized_username, empresa_id
            )
            if existing and existing.id != user_id:
                raise UsuarioAlreadyExistsError(
                    "Ya existe un usuario con ese username en la empresa"
                )
            updates["username"] = normalized_username

        for field in ("nombre", "apellido", "telefono"):
            if field in updates and isinstance(updates[field], str):
                updates[field] = updates[field].strip()

        if role_ids is not None:
            if not role_ids:
                raise UsuarioWithoutRoleError("El usuario debe tener al menos un rol asignado")
            if not await self.usuario_repository.role_ids_belong_to_empresa(role_ids, empresa_id):
                raise InvalidRoleForEmpresaError("Uno o más roles no pertenecen a la empresa")
            if (
                usuario.is_active
                and await self.usuario_repository.user_has_admin_role(user_id, empresa_id)
                and not await self.usuario_repository.role_ids_include_admin(role_ids, empresa_id)
                and await self.usuario_repository.count_active_admins(empresa_id) <= 1
            ):
                raise LastAdminCannotBeDisabledError(
                    "No se puede retirar el rol al último administrador activo de la empresa"
                )

        return await self.usuario_repository.update_usuario(
            user_id=user_id,
            empresa_id=empresa_id,
            values=updates,
            role_ids=role_ids,
        )
