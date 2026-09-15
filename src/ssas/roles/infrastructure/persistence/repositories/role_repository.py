from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ssas.roles.domain.entities.role import Role
from ssas.roles.infrastructure.persistence.models.role import RoleModel


class SqlAlchemyRoleRepository:
    def __init__(self, session: AsyncSession, empresa_id: str | None):
        self.session = session
        self.empresa_id = empresa_id

    async def create(self, role: Role) -> Role:
        model = RoleModel(
            id=role.id,
            empresa_id=role.empresa_id,
            name=role.name,
            codigo=role.codigo,
            description=role.description,
            es_base=role.es_base,
            is_active=role.is_active,
        )
        self.session.add(model)
        await self.session.flush()
        return role

    async def list(self) -> list[Role]:
        result = await self.session.execute(
            select(RoleModel)
            .options(selectinload(RoleModel.permissions))
            .where(RoleModel.empresa_id == self.empresa_id)
            .order_by(RoleModel.name)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_id(self, role_id: str) -> Role | None:
        result = await self.session.execute(
            select(RoleModel)
            .options(selectinload(RoleModel.permissions))
            .where(RoleModel.id == role_id, RoleModel.empresa_id == self.empresa_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_name(self, name: str) -> Role | None:
        result = await self.session.execute(
            select(RoleModel).where(
                RoleModel.empresa_id == self.empresa_id,
                func.lower(RoleModel.name) == name.strip().lower(),
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_code(self, code: str) -> Role | None:
        result = await self.session.execute(
            select(RoleModel).where(
                RoleModel.empresa_id == self.empresa_id,
                func.lower(RoleModel.codigo) == code.strip().lower(),
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def update(self, role_id: str, values: dict) -> Role:
        result = await self.session.execute(
            select(RoleModel)
            .options(selectinload(RoleModel.permissions))
            .where(RoleModel.id == role_id, RoleModel.empresa_id == self.empresa_id)
        )
        model = result.scalar_one_or_none()
        for field, value in values.items():
            setattr(model, field, value)
        await self.session.flush()
        return self._to_entity(model)

    async def delete(self, role_id: str) -> None:
        await self.session.execute(
            update(RoleModel).where(
                RoleModel.id == role_id,
                RoleModel.empresa_id == self.empresa_id,
            ).values(is_active=False)
        )
        await self.session.flush()

    async def assign_permissions(self, role_id: str, permissions: list) -> Role:
        result = await self.session.execute(
            select(RoleModel)
            .options(selectinload(RoleModel.permissions))
            .where(RoleModel.id == role_id, RoleModel.empresa_id == self.empresa_id)
        )
        model = result.scalar_one()
        model.permissions = [permission_model for permission_model in permissions]
        await self.session.flush()
        return self._to_entity(model)

    @staticmethod
    def _to_entity(model: RoleModel) -> Role:
        from ssas.roles.infrastructure.persistence.repositories.permission_repository import (
            PermissionRepository,
        )

        return Role(
            id=model.id,
            empresa_id=model.empresa_id,
            name=model.name,
            codigo=model.codigo,
            description=model.description,
            es_base=model.es_base,
            is_active=model.is_active,
            permissions=[
                PermissionRepository.to_entity(permission) for permission in model.permissions
            ],
        )
