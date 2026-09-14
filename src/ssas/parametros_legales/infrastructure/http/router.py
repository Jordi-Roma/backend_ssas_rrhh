from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.events.parametros_legales_events import (
    ParametrosLegalesEvents,
)
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.api.openapi import AUTHENTICATED_RESPONSES, TAG_CONFIGURACION
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_empresa_permission
from ssas.infrastructure.database.session import get_session
from ssas.parametros_legales.application.use_cases.gestionar_parametros import (
    GestionarParametrosLegales,
)
from ssas.parametros_legales.domain.exceptions import (
    ParametroLegalError,
    ParametroLegalNotFoundError,
    ParametroLegalOverlapError,
    ParametroLegalPercentError,
    ParametroLegalRangeError,
)
from ssas.parametros_legales.infrastructure.http.schemas import (
    ActualizarParametroLegalRequest,
    ParametroLegalRequest,
    ParametroLegalResponse,
)
from ssas.parametros_legales.infrastructure.persistence.repositories.parametro_legal_repository import (
    SqlAlchemyParametroLegalRepository,
)

router = APIRouter(
    prefix="/parametros-legales",
    tags=[TAG_CONFIGURACION],
    responses=AUTHENTICATED_RESPONSES,
)


def _repo(session: AsyncSession) -> SqlAlchemyParametroLegalRepository:
    return SqlAlchemyParametroLegalRepository(session)


def _service(session: AsyncSession) -> GestionarParametrosLegales:
    return GestionarParametrosLegales(_repo(session))


def _events(session: AsyncSession) -> ParametrosLegalesEvents:
    repository = SqlAlchemyAuditLogRepository(session)
    return ParametrosLegalesEvents(RegisterAuditEvent(repository))


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


def _raise_http_parametro_error(exc: ParametroLegalError) -> None:
    if isinstance(exc, ParametroLegalNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, ParametroLegalOverlapError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, (ParametroLegalRangeError, ParametroLegalPercentError)):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(exc)) from exc


def _payload(periodo) -> ParametroLegalResponse:
    return ParametroLegalResponse(
        id=periodo.id,
        empresa_id=periodo.empresa_id,
        vigencia_desde=periodo.vigencia_desde,
        vigencia_hasta=periodo.vigencia_hasta,
        afp=periodo.afp,
        aporte_solidario=periodo.aporte_solidario,
        rc_iva=periodo.rc_iva,
        aguinaldo=periodo.aguinaldo,
        prima=periodo.prima,
        vigente=periodo.vigente,
        created_at=periodo.created_at,
        updated_at=periodo.updated_at,
    )


@router.get(
    "",
    response_model=list[ParametroLegalResponse],
    summary="Listar parámetros legales",
    description=(
        "Lista los periodos de parámetros legales de la empresa autorizada, ordenados "
        "del más reciente al más antiguo; solo lectura. Permisos: `empresa:ver` o "
        "`platform:empresas:ver`."
    ),
)
async def listar_parametros(
    empresa_id: str | None = Query(default=None, description="Identificador de empresa."),
    current_user: CurrentUser = Depends(
        require_empresa_permission("empresa:ver", "platform:empresas:ver")
    ),
    session: AsyncSession = Depends(get_session),
):
    periodos = await _service(session).listar(_target_empresa(current_user, empresa_id))
    return [_payload(p) for p in periodos]


@router.post(
    "",
    response_model=ParametroLegalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar periodo de parámetros legales",
    description=(
        "Crea un periodo de vigencia con los parámetros legales (AFP, aporte solidario, "
        "RC-IVA, aguinaldo, prima). Valida rango y evita solapamientos con otros "
        "periodos. Requiere `empresa:editar` o `platform:empresas:editar`. Queda "
        "registrado en la bitácora."
    ),
    responses={
        409: {"description": "El periodo se solapa con otro ya registrado."},
        422: {"description": "Rango de fechas o porcentajes fuera de lo permitido."},
    },
)
async def crear_parametros(
    body: ParametroLegalRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description="Identificador de empresa."),
    current_user: CurrentUser = Depends(
        require_empresa_permission("empresa:editar", "platform:empresas:editar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        periodo = await _service(session).crear(
            _target_empresa(current_user, empresa_id), body.model_dump()
        )
    except ParametroLegalError as exc:
        _raise_http_parametro_error(exc)
    await _events(session).periodo_creado(
        record_id=periodo.id,
        new_data={
            "vigencia_desde": str(periodo.vigencia_desde),
            "vigencia_hasta": str(periodo.vigencia_hasta),
            "afp": str(periodo.afp),
        },
        **_audit_context(http_request, current_user),
    )
    return _payload(periodo)


@router.put(
    "/{periodo_id}",
    response_model=ParametroLegalResponse,
    summary="Actualizar periodo de parámetros legales",
    description=(
        "Actualiza los parámetros o la vigencia de un periodo de la empresa autorizada, "
        "manteniendo el historial. Valida solapamientos contra los demás periodos. "
        "Requiere `empresa:editar` o `platform:empresas:editar`."
    ),
    responses={
        404: {"description": "Periodo no encontrado."},
        409: {"description": "El periodo se solapa con otro ya registrado."},
    },
)
async def actualizar_parametros(
    periodo_id: str,
    body: ActualizarParametroLegalRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description="Identificador de empresa."),
    current_user: CurrentUser = Depends(
        require_empresa_permission("empresa:editar", "platform:empresas:editar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        periodo = await _service(session).actualizar(
            periodo_id,
            _target_empresa(current_user, empresa_id),
            body.model_dump(exclude_unset=True),
        )
    except ParametroLegalError as exc:
        _raise_http_parametro_error(exc)
    await _events(session).periodo_actualizado(
        record_id=periodo.id,
        new_data={
            "vigencia_desde": str(periodo.vigencia_desde),
            "vigencia_hasta": str(periodo.vigencia_hasta),
            "afp": str(periodo.afp),
        },
        **_audit_context(http_request, current_user),
    )
    return _payload(periodo)
