from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.events.role_events import RoleEvents
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.api.openapi import (
    AUTHENTICATED_RESPONSES,
    EMPRESA_SCOPE_DESCRIPTION,
    TAG_ROLES,
)
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.infrastructure.database.session import get_session
from ssas.modulos.application.module_access import get_modulos_habilitados
from ssas.roles.application.use_cases.assign_permissions import AssignPermissions
from ssas.roles.application.use_cases.create_role import CreateRole
from ssas.roles.application.use_cases.delete_role import DeleteRole
from ssas.roles.application.use_cases.get_role import GetRole
from ssas.roles.application.use_cases.list_roles import ListRoles
from ssas.roles.application.use_cases.update_role import UpdateRole
from ssas.roles.domain.exceptions import (
    DuplicateRoleError,
    PermissionNotFoundError,
    ProtectedRoleError,
    RoleNotFoundError,
)
from ssas.roles.infrastructure.http.schemas import (
    AssignPermissionsRequest,
    CreateRoleRequest,
    RoleSchema,
    UpdateRoleRequest,
)
from ssas.roles.infrastructure.persistence.models.permission import PermissionModel
from ssas.roles.infrastructure.persistence.repositories.permission_repository import (
    PermissionRepository,
)
from ssas.roles.infrastructure.persistence.repositories.role_repository import (
    SqlAlchemyRoleRepository,
)

router = APIRouter(prefix="/roles", tags=[TAG_ROLES], responses=AUTHENTICATED_RESPONSES)

PREFIJO_PLATAFORMA = "platform:"


def _repository(session: AsyncSession, empresa_id: str | None) -> SqlAlchemyRoleRepository:
    return SqlAlchemyRoleRepository(session, empresa_id)


def _target_empresa(current_user: CurrentUser, requested: str | None) -> str | None:
    if current_user.es_plataforma:
        return requested
    if requested is not None and requested != current_user.empresa_id:
        raise HTTPException(status_code=403, detail="No puedes operar sobre otra empresa")
    return current_user.empresa_id


def _audit_context(request: Request, current_user: CurrentUser) -> dict[str, str | None]:
    return {
        "empresa_id": current_user.empresa_id,
        "user_id": current_user.id,
        "source_ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


def _events(session: AsyncSession) -> RoleEvents:
    repository = SqlAlchemyAuditLogRepository(session)
    return RoleEvents(RegisterAuditEvent(repository))


@router.get(
    "",
    response_model=list[RoleSchema],
    summary="Listar roles",
    description=(
        "Lista los roles disponibles en el alcance seleccionado. Permiso: "
        "`roles:gestionar` para empresa o `platform:usuarios:gestionar` para plataforma."
    ),
    responses={409: {"description": "Ya existe un rol con el mismo código en el alcance."}},
)
async def list_roles(
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    return await ListRoles(
        _repository(session, _target_empresa(current_user, empresa_id))
    ).execute()


@router.post(
    "",
    response_model=RoleSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Crear rol",
    description=(
        "Crea un rol dentro del alcance seleccionado. Los códigos de rol deben ser únicos "
        "en ese alcance."
    ),
)
async def create_role(
    request: CreateRoleRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        target_empresa = _target_empresa(current_user, empresa_id)
        role = await CreateRole(_repository(session, target_empresa)).execute(
            empresa_id=target_empresa,
            **request.model_dump(),
        )
        await _events(session).created(
            record_id=role.id,
            new_data={"nombre": role.name, "codigo": role.codigo},
            **_audit_context(http_request, current_user),
        )
        return role
    except DuplicateRoleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/{role_id}",
    response_model=RoleSchema,
    summary="Consultar rol",
    description="Obtiene el rol y los permisos que tiene asignados dentro del alcance autorizado.",
    responses={404: {"description": "Rol no encontrado dentro del alcance."}},
)
async def get_role(
    role_id: str,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await GetRole(
            _repository(session, _target_empresa(current_user, empresa_id))
        ).execute(role_id)
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/{role_id}",
    response_model=RoleSchema,
    summary="Actualizar rol",
    description="Actualiza los campos enviados sin modificar los permisos que ya tiene asignados.",
    responses={
        404: {"description": "Rol no encontrado dentro del alcance."},
        409: {"description": "Ya existe un rol con el mismo código en el alcance."},
    },
)
async def update_role(
    role_id: str,
    request: UpdateRoleRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        values = request.model_dump(exclude_unset=True)
        role = await UpdateRole(
            _repository(session, _target_empresa(current_user, empresa_id))
        ).execute(role_id, values)
        await _events(session).updated(
            record_id=role.id,
            new_data=values,
            **_audit_context(http_request, current_user),
        )
        return role
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DuplicateRoleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProtectedRoleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete(
    "/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar rol",
    description="Elimina un rol del alcance autorizado cuando no está protegido por reglas del sistema.",
    responses={404: {"description": "Rol no encontrado dentro del alcance."}},
)
async def delete_role(
    role_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        await DeleteRole(_repository(session, _target_empresa(current_user, empresa_id))).execute(
            role_id
        )
        await _events(session).deleted(
            record_id=role_id,
            **_audit_context(http_request, current_user),
        )
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProtectedRoleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put(
    "/{role_id}/permissions",
    response_model=RoleSchema,
    summary="Reemplazar permisos del rol",
    description=(
        "Reemplaza el conjunto completo de permisos del rol. Los permisos deben existir y "
        "ser válidos para el alcance."
    ),
    responses={404: {"description": "El rol o alguno de los permisos no existe."}},
)
async def assign_permissions(
    role_id: str,
    request: AssignPermissionsRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        role = await AssignPermissions(
            _repository(session, _target_empresa(current_user, empresa_id)),
            PermissionRepository(session),
        ).execute(role_id, request.permission_ids)
        await _events(session).permissions_assigned(
            record_id=role_id,
            new_data={"permission_ids": request.permission_ids},
            **_audit_context(http_request, current_user),
        )
        return role
    except RoleNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProtectedRoleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


permisos_router = APIRouter(
    prefix="/permisos", tags=[TAG_ROLES], responses=AUTHENTICATED_RESPONSES
)


class PermisoSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    codigo: str = Field(validation_alias="name")
    modulo: str
    recurso: str = Field(validation_alias="resource")
    operacion: str = Field(validation_alias="action")
    descripcion: str | None = Field(default=None, validation_alias="description")


@permisos_router.get(
    "",
    response_model=list[PermisoSchema],
    summary="Catálogo de permisos asignables",
    description=(
        "Permisos que el alcance actual puede asignar a un rol. Un administrador de "
        "empresa nunca ve los permisos `platform:*` ni los de módulos que su empresa "
        "no tiene habilitados."
    ),
)
async def list_permisos(
    current_user: CurrentUser = Depends(
        require_scoped_permission("roles:gestionar", "platform:usuarios:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    statement = select(PermissionModel).order_by(
        PermissionModel.modulo, PermissionModel.resource, PermissionModel.action
    )
    if not current_user.es_plataforma:
        habilitados = await get_modulos_habilitados(session, current_user.empresa_id)
        statement = statement.where(
            PermissionModel.modulo.in_(habilitados),
            ~PermissionModel.name.startswith(PREFIJO_PLATAFORMA),
        )
    result = await session.execute(statement)
    return result.scalars().all()
