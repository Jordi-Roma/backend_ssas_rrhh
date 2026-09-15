from abc import ABC, abstractmethod

from ssas.usuarios.domain.entities.usuario import Usuario


class UsuarioRepository(ABC):
    @abstractmethod
    async def list_usuarios(
        self,
        empresa_id: str | None,
        search: str | None,
        is_active: bool | None,
        page: int,
        per_page: int,
        include_deleted: bool = False,
    ) -> tuple[list[Usuario], int]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(
        self, user_id: str, empresa_id: str | None, include_deleted: bool = False
    ) -> Usuario | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_email(self, email: str, empresa_id: str | None) -> Usuario | None:
        raise NotImplementedError

    @abstractmethod
    async def get_by_username(self, username: str, empresa_id: str | None) -> Usuario | None:
        raise NotImplementedError

    @abstractmethod
    async def create_usuario(
        self,
        empresa_id: str | None,
        nombre: str,
        apellido: str,
        email: str,
        username: str,
        password_hash: str,
        telefono: str | None,
        role_ids: list[str],
        email_verificado: bool = True,
    ) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def update_usuario(
        self,
        user_id: str,
        empresa_id: str | None,
        values: dict,
        role_ids: list[str] | None = None,
    ) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def activate_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def deactivate_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def soft_delete_usuario(
        self, user_id: str, empresa_id: str | None, actor_id: str
    ) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def restore_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def role_ids_belong_to_empresa(self, role_ids: list[str], empresa_id: str | None) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def count_active_admins(self, empresa_id: str | None) -> int:
        raise NotImplementedError

    @abstractmethod
    async def user_has_admin_role(self, user_id: str, empresa_id: str | None) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def role_ids_include_admin(
        self, role_ids: list[str], empresa_id: str | None
    ) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def assign_roles(self, user_id: str, role_ids: list[str]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def set_password(
        self, user_id: str, empresa_id: str | None, password_hash: str, must_change: bool
    ) -> Usuario:
        raise NotImplementedError

    @abstractmethod
    async def unlock_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        raise NotImplementedError
