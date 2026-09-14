from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.events.organizacion_events import OrganizacionEvents
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.cargos.application.use_cases.actualizar_cargo import ActualizarCargo
from ssas.cargos.application.use_cases.crear_cargo import CrearCargo
from ssas.cargos.application.use_cases.eliminar_cargo import EliminarCargo
from ssas.cargos.application.use_cases.listar_cargos import ListarCargos
from ssas.cargos.domain.exceptions import (
    CargoAlreadyExistsError,
    CargoError,
    CargoInUseError,
    CargoNotFoundError,
    InvalidDepartamentoForCargoError,
)
from ssas.cargos.infrastructure.http.schemas import (
    ActualizarCargoRequest,
    CargoResponse,
    CrearCargoRequest,
)
from ssas.cargos.infrastructure.persistence.repositories.cargo_repository import (
    SqlAlchemyCargoRepository,
)
from ssas.core.api.openapi import AUTHENTICATED_RESPONSES, EMPRESA_SCOPE_DESCRIPTION, TAG_CARGOS
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.infrastructure.database.session import get_session

router = APIRouter(
    prefix="/cargos",
    tags=[TAG_CARGOS],
    responses=AUTHENTICATED_RESPONSES,
)


def _events(session: AsyncSession) -> OrganizacionEvents:
    repository = SqlAlchemyAuditLogRepository(session)
    return OrganizacionEvents(RegisterAuditEvent(repository))


def _audit_context(request: Request, current_user: CurrentUser) -> dict[str, str | None]:
    return {
        "empresa_id": current_user.empresa_id,
        "user_id": current_user.id,
        "source_ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


def _target_empresa(current_user: CurrentUser, requested: str | None) -> str:
    if current_user.es_plataforma:
        if requested is None:
            raise HTTPException(status_code=422, detail="Debe indicar empresa_id")
        return requested
    if requested is not None and requested != current_user.empresa_id:
        raise HTTPException(status_code=403, detail="No puedes operar sobre otra empresa")
    if current_user.empresa_id is None:
        raise HTTPException(status_code=403, detail="No tienes una empresa asignada")
    return current_user.empresa_id


def _repository(session: AsyncSession) -> SqlAlchemyCargoRepository:
    return SqlAlchemyCargoRepository(session)


def _raise_http_cargo_error(exc: CargoError) -> None:
    if isinstance(exc, CargoNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (CargoAlreadyExistsError, CargoInUseError)):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, InvalidDepartamentoForCargoError):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.get(
    "",
    response_model=list[CargoResponse],
    summary="Listar cargos",
    description=(
        "Lista cargos del alcance autorizado. Permisos: `cargos:ver` "
        "o `platform:organizacion:gestionar`."
    ),
)
async def listar_cargos(
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    activo: bool | None = Query(default=None, description="Filtra por estado activo."),
    departamento_id: str | None = Query(default=None, description="Filtra por departamento."),
    current_user: CurrentUser = Depends(
        require_scoped_permission("cargos:ver", "platform:organizacion:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    return await ListarCargos(_repository(session)).execute(
        _target_empresa(current_user, empresa_id),
        activo,
        departamento_id,
    )


@router.post(
    "",
    response_model=CargoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear cargo",
    description=(
        "Crea un cargo dentro de la empresa autorizada y valida que su departamento "
        "pertenezca al mismo alcance. Requiere `cargos:crear` o "
        "`platform:organizacion:gestionar`."
    ),
    responses={
        409: {"description": "Ya existe un cargo con ese nombre."},
        422: {"description": "El departamento no pertenece a la empresa."},
    },
)
async def crear_cargo(
    request: CrearCargoRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("cargos:crear", "platform:organizacion:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        cargo = await CrearCargo(_repository(session)).execute(
            empresa_id=_target_empresa(current_user, empresa_id),
            **request.model_dump(),
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="El cargo ya existe") from exc
    except CargoError as exc:
        _raise_http_cargo_error(exc)
    await _events(session).cargo_creado(
        record_id=cargo.id,
        new_data={"nombre": cargo.nombre},
        **_audit_context(http_request, current_user),
    )
    return cargo


@router.put(
    "/{cargo_id}",
    response_model=CargoResponse,
    summary="Actualizar cargo",
    description=(
        "Actualiza un cargo de la empresa autorizada y valida el departamento indicado. "
        "Requiere `cargos:editar` o `platform:organizacion:gestionar`."
    ),
    responses={
        404: {"description": "Cargo no encontrado."},
        409: {"description": "Ya existe un cargo con ese nombre."},
        422: {"description": "El departamento no pertenece a la empresa."},
    },
)
async def actualizar_cargo(
    cargo_id: str,
    request: ActualizarCargoRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("cargos:editar", "platform:organizacion:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        cargo = await ActualizarCargo(_repository(session)).execute(
            cargo_id,
            _target_empresa(current_user, empresa_id),
            request.model_dump(exclude_unset=True),
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="El cargo ya existe") from exc
    except CargoError as exc:
        _raise_http_cargo_error(exc)
    await _events(session).cargo_actualizado(
        record_id=cargo.id,
        new_data={"nombre": cargo.nombre},
        **_audit_context(http_request, current_user),
    )
    return cargo


@router.delete(
    "/{cargo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar cargo",
    description=(
        "Elimina un cargo sin dependencias dentro de la empresa autorizada. Requiere "
        "`cargos:eliminar` o `platform:organizacion:gestionar`."
    ),
    responses={
        404: {"description": "Cargo no encontrado."},
        409: {"description": "El cargo tiene dependencias."},
    },
)
async def eliminar_cargo(
    cargo_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("cargos:eliminar", "platform:organizacion:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        await EliminarCargo(_repository(session)).execute(
            cargo_id, _target_empresa(current_user, empresa_id)
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="El cargo tiene dependencias") from exc
    except CargoError as exc:
        _raise_http_cargo_error(exc)
    await _events(session).cargo_eliminado(
        record_id=cargo_id,
        **_audit_context(http_request, current_user),
    )
