from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.roles.infrastructure.persistence.models.role import RoleModel
from ssas.roles.infrastructure.persistence.models.user_role import usuario_rol_table
from ssas.usuarios.domain.entities.usuario import Usuario
from ssas.usuarios.domain.exceptions import UsuarioNotFoundError
from ssas.usuarios.ports.outgoing.usuario_repository import UsuarioRepository

ADMIN_ROLE_CODE = "ADMIN_EMPRESA"
ADMIN_ROLE_NAME = "Administrador de Empresa"


class SqlAlchemyUsuarioRepository(UsuarioRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_usuarios(
        self,
        empresa_id: str | None,
        search: str | None,
        is_active: bool | None,
        page: int,
        per_page: int,
        include_deleted: bool = False,
    ) -> tuple[list[Usuario], int]:
        conditions = [UserModel.empresa_id == empresa_id]
        if not include_deleted:
            conditions.append(UserModel.eliminado_at.is_(None))
        if is_active is not None:
            conditions.append(UserModel.is_active.is_(is_active))
        if search:
            term = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(UserModel.name).like(term),
                    func.lower(UserModel.apellido).like(term),
                    func.lower(UserModel.email).like(term),
                    func.lower(UserModel.username).like(term),
                )
            )
        total = (
            await self.session.execute(select(func.count(UserModel.id)).where(*conditions))
        ).scalar_one()
        result = await self.session.execute(
            self._base_query()
            .where(*conditions)
            .order_by(UserModel.name, UserModel.apellido)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        return [self._to_entity(model) for model in result.scalars().unique().all()], total

    async def get_by_id(
        self, user_id: str, empresa_id: str | None, include_deleted: bool = False
    ) -> Usuario | None:
        conditions = [UserModel.id == user_id, UserModel.empresa_id == empresa_id]
        if not include_deleted:
            conditions.append(UserModel.eliminado_at.is_(None))
        result = await self.session.execute(
            self._base_query().where(*conditions)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: str, empresa_id: str | None) -> Usuario | None:
        result = await self.session.execute(
            self._base_query().where(
                UserModel.empresa_id == empresa_id,
                func.lower(UserModel.email) == email.strip().lower(),
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_username(self, username: str, empresa_id: str | None) -> Usuario | None:
        result = await self.session.execute(
            self._base_query().where(
                UserModel.empresa_id == empresa_id,
                func.lower(UserModel.username) == username.strip().lower(),
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

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
        user_id = str(uuid4())
        self.session.add(
            UserModel(
                id=user_id,
                empresa_id=empresa_id,
                name=nombre,
                apellido=apellido,
                email=email,
                username=username,
                hashed_password=password_hash,
                telefono=telefono,
                is_active=True,
                # Lo crea un administrador que ya conoce al titular y le fija una
                # contraseña provisional: exigir además verificación de correo dejaba
                # la cuenta inutilizable si el envío de correo no está operativo.
                # La seguridad la cubre `debe_cambiar_password`.
                email_verified=email_verificado,
                debe_cambiar_password=True,
            )
        )
        await self.session.flush()
        await self.assign_roles(user_id, role_ids)
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado después de crearlo")
        return usuario

    async def update_usuario(
        self,
        user_id: str,
        empresa_id: str | None,
        values: dict,
        role_ids: list[str] | None = None,
    ) -> Usuario:
        db_values = self._to_db_values(values)
        if db_values:
            await self.session.execute(
                update(UserModel)
                .where(UserModel.id == user_id, UserModel.empresa_id == empresa_id)
                .values(**db_values)
            )
        if role_ids is not None:
            await self.assign_roles(user_id, role_ids)
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    async def activate_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        await self.session.execute(
            update(UserModel)
            .where(
                UserModel.id == user_id,
                UserModel.empresa_id == empresa_id,
                UserModel.eliminado_at.is_(None),
            )
            .values(is_active=True)
        )
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    async def deactivate_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        await self.session.execute(
            update(UserModel)
            .where(UserModel.id == user_id, UserModel.empresa_id == empresa_id)
            .values(is_active=False)
        )
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    async def soft_delete_usuario(
        self, user_id: str, empresa_id: str | None, actor_id: str
    ) -> Usuario:
        await self.session.execute(
            update(UserModel)
            .where(
                UserModel.id == user_id,
                UserModel.empresa_id == empresa_id,
                UserModel.eliminado_at.is_(None),
            )
            .values(
                is_active=False,
                eliminado_at=datetime.now(UTC),
                eliminado_por_id=actor_id,
            )
        )
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id, include_deleted=True)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    async def restore_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        await self.session.execute(
            update(UserModel)
            .where(
                UserModel.id == user_id,
                UserModel.empresa_id == empresa_id,
                UserModel.eliminado_at.is_not(None),
            )
            .values(is_active=False, eliminado_at=None, eliminado_por_id=None)
        )
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    async def role_ids_belong_to_empresa(self, role_ids: list[str], empresa_id: str | None) -> bool:
        unique_role_ids = set(role_ids)
        if not unique_role_ids:
            return False
        result = await self.session.execute(
            select(func.count(RoleModel.id)).where(
                RoleModel.id.in_(unique_role_ids),
                RoleModel.empresa_id == empresa_id,
                RoleModel.is_active.is_(True),
            )
        )
        return result.scalar_one() == len(unique_role_ids)

    async def count_active_admins(self, empresa_id: str | None) -> int:
        result = await self.session.execute(
            select(func.count(func.distinct(UserModel.id)))
            .select_from(UserModel)
            .join(usuario_rol_table, usuario_rol_table.c.usuario_id == UserModel.id)
            .join(RoleModel, RoleModel.id == usuario_rol_table.c.rol_id)
            .where(
                UserModel.empresa_id == empresa_id,
                UserModel.is_active.is_(True),
                UserModel.eliminado_at.is_(None),
                RoleModel.empresa_id == empresa_id,
                RoleModel.is_active.is_(True),
                self._admin_role_filter(empresa_id),
            )
        )
        return result.scalar_one()

    async def user_has_admin_role(self, user_id: str, empresa_id: str | None) -> bool:
        result = await self.session.execute(
            select(func.count(RoleModel.id))
            .select_from(UserModel)
            .join(usuario_rol_table, usuario_rol_table.c.usuario_id == UserModel.id)
            .join(RoleModel, RoleModel.id == usuario_rol_table.c.rol_id)
            .where(
                UserModel.id == user_id,
                UserModel.empresa_id == empresa_id,
                RoleModel.empresa_id == empresa_id,
                RoleModel.is_active.is_(True),
                self._admin_role_filter(empresa_id),
            )
        )
        return result.scalar_one() > 0

    async def role_ids_include_admin(
        self, role_ids: list[str], empresa_id: str | None
    ) -> bool:
        if not role_ids:
            return False
        result = await self.session.execute(
            select(func.count(RoleModel.id)).where(
                RoleModel.id.in_(set(role_ids)),
                RoleModel.empresa_id == empresa_id,
                RoleModel.is_active.is_(True),
                self._admin_role_filter(empresa_id),
            )
        )
        return result.scalar_one() > 0

    async def assign_roles(self, user_id: str, role_ids: list[str]) -> None:
        await self.session.execute(
            delete(usuario_rol_table).where(usuario_rol_table.c.usuario_id == user_id)
        )
        if role_ids:
            await self.session.execute(
                insert(usuario_rol_table),
                [{"usuario_id": user_id, "rol_id": role_id} for role_id in set(role_ids)],
            )
        await self.session.flush()

    async def set_password(
        self, user_id: str, empresa_id: str | None, password_hash: str, must_change: bool
    ) -> Usuario:
        await self.session.execute(
            update(UserModel)
            .where(UserModel.id == user_id, UserModel.empresa_id == empresa_id)
            .values(hashed_password=password_hash, debe_cambiar_password=must_change)
        )
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    async def unlock_usuario(self, user_id: str, empresa_id: str | None) -> Usuario:
        await self.session.execute(
            update(UserModel)
            .where(UserModel.id == user_id, UserModel.empresa_id == empresa_id)
            .values(intentos_fallidos=0, bloqueado_hasta=None, ultimo_intento_fallido=None)
        )
        await self.session.flush()
        usuario = await self.get_by_id(user_id, empresa_id)
        if usuario is None:
            raise UsuarioNotFoundError("Usuario no encontrado")
        return usuario

    @staticmethod
    def _base_query():
        return select(UserModel).options(selectinload(UserModel.roles))

    @staticmethod
    def _admin_role_filter(empresa_id: str | None):
        if empresa_id is None:
            return RoleModel.codigo == "SUPER_ADMIN"
        return (RoleModel.codigo == ADMIN_ROLE_CODE) | (RoleModel.name == ADMIN_ROLE_NAME)

    @staticmethod
    def _to_db_values(values: dict) -> dict:
        mapping = {
            "nombre": "name",
            "apellido": "apellido",
            "email": "email",
            "username": "username",
            "telefono": "telefono",
        }
        return {mapping[key]: value for key, value in values.items() if key in mapping}

    @staticmethod
    def _to_entity(model: UserModel) -> Usuario:
        return Usuario(
            id=model.id,
            empresa_id=model.empresa_id,
            nombre=model.name,
            apellido=model.apellido,
            email=model.email,
            username=model.username,
            telefono=model.telefono,
            is_active=model.is_active,
            email_verified=model.email_verified,
            must_change_password=model.debe_cambiar_password,
            failed_login_attempts=model.intentos_fallidos,
            locked_until=model.bloqueado_hasta,
            eliminado_at=model.eliminado_at,
            eliminado_por_id=model.eliminado_por_id,
            roles=[role.name for role in model.roles if role.is_active],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
