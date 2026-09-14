from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.events.vacante_events import VacanteEvents
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.api.openapi import EMPRESA_SCOPE_DESCRIPTION, TAG_VACANTES
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.infrastructure.database.session import get_session
from ssas.vacantes.application.use_cases.gestionar_vacantes import GestionarVacantes
from ssas.vacantes.domain.exceptions import (
    VacanteError,
    VacanteInvalidStateError,
    VacanteNotFoundError,
    VacanteReferenceError,
)
from ssas.vacantes.infrastructure.http.schemas import (
    ActualizarVacanteRequest,
    CrearVacanteRequest,
    EmpresaPublicaResponse,
    VacantePublicaResponse,
    VacanteResponse,
)
from ssas.vacantes.infrastructure.persistence.repositories.vacante_repository import (
    SqlAlchemyVacanteRepository,
)

router = APIRouter(prefix="/vacantes", tags=[TAG_VACANTES])
public_router = APIRouter(prefix="/publico", tags=["Portal público"])


def _empresa(current_user: CurrentUser, requested: str | None) -> str:
    if current_user.es_plataforma:
        if requested is None:
            raise HTTPException(status_code=422, detail="Debe indicar empresa_id")
        return requested
    if current_user.empresa_id is None:
        raise HTTPException(status_code=403, detail="No tienes una empresa asignada")
    if requested is not None and requested != current_user.empresa_id:
        raise HTTPException(status_code=403, detail="No puedes operar sobre otra empresa")
    return current_user.empresa_id


def _service(session: AsyncSession) -> GestionarVacantes:
    return GestionarVacantes(SqlAlchemyVacanteRepository(session))


def _audit_context(request: Request, current_user: CurrentUser) -> dict[str, str | None]:
    return {
        "empresa_id": current_user.empresa_id,
        "user_id": current_user.id,
        "source_ip": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


def _events(session: AsyncSession) -> VacanteEvents:
    repository = SqlAlchemyAuditLogRepository(session)
    return VacanteEvents(RegisterAuditEvent(repository))


def _raise(exc: VacanteError) -> None:
    if isinstance(exc, VacanteNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, (VacanteInvalidStateError, VacanteReferenceError)):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(exc)) from exc


async def _responsable_vacante(
    session: AsyncSession, current_user: CurrentUser, empresa_id: str
) -> str:
    """Resuelve el responsable de una vacante nueva.

    El responsable queda siempre a nombre de la empresa donde se publica: si el
    usuario pertenece a esa empresa se usa él mismo; los usuarios de plataforma
    operan sobre empresas ajenas y entonces se asigna el primer miembro activo.
    """
    if current_user.empresa_id == empresa_id:
        return current_user.id
    from sqlalchemy import select

    from ssas.auth.infrastructure.persistence.models.user import UserModel

    result = await session.execute(
        select(UserModel.id)
        .where(
            UserModel.empresa_id == empresa_id,
            UserModel.is_active.is_(True),
            UserModel.eliminado_at.is_(None),
        )
        .order_by(UserModel.created_at.asc())
        .limit(1)
    )
    responsable_id = result.scalar_one_or_none()
    if responsable_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="La empresa seleccionada no tiene usuarios activos para asignar "
            "como responsable de la vacante. Registra o activa un miembro primero.",
        )
    return str(responsable_id)


@router.get(
    "",
    response_model=list[VacanteResponse],
    summary="Listar vacantes",
    description="Lista las vacantes del alcance autorizado.",
)
async def listar_vacantes(
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    estado: str | None = Query(default=None),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:ver", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    return await _service(session).listar(_empresa(current_user, empresa_id), estado)


@router.post(
    "",
    response_model=VacanteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear vacante",
    description="Crea una vacante en la empresa autorizada.",
)
async def crear_vacante(
    request: CrearVacanteRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:crear", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        empresa_id = _empresa(current_user, empresa_id)
        responsable_id = await _responsable_vacante(session, current_user, empresa_id)
        vacante = await _service(session).crear(empresa_id, responsable_id, request.model_dump())
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="No se pudo crear la vacante") from exc
    except VacanteError as exc:
        _raise(exc)
    await _events(session).created(
        record_id=vacante.id,
        new_data={"titulo": vacante.titulo, "estado": vacante.estado},
        **_audit_context(http_request, current_user),
    )
    return vacante


@router.get(
    "/{vacante_id}",
    response_model=VacanteResponse,
    summary="Obtener vacante",
    description="Obtiene una vacante de la empresa autorizada.",
)
async def obtener_vacante(
    vacante_id: str,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:ver", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await _service(session).obtener(vacante_id, _empresa(current_user, empresa_id))
    except VacanteError as exc:
        _raise(exc)


@router.put(
    "/{vacante_id}",
    response_model=VacanteResponse,
    summary="Actualizar vacante",
    description="Actualiza una vacante que todavía está en borrador.",
)
async def actualizar_vacante(
    vacante_id: str,
    request: ActualizarVacanteRequest,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:editar", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        values = request.model_dump(exclude_unset=True)
        vacante = await _service(session).actualizar(
            vacante_id,
            _empresa(current_user, empresa_id),
            values,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="No se pudo actualizar la vacante") from exc
    except VacanteError as exc:
        _raise(exc)
    await _events(session).updated(
        record_id=vacante.id,
        new_data={"titulo": values.get("titulo", vacante.titulo), "estado": vacante.estado},
        **_audit_context(http_request, current_user),
    )
    return vacante


@router.patch(
    "/{vacante_id}/publicar",
    response_model=VacanteResponse,
    summary="Publicar vacante",
    description="Publica una vacante en el portal público.",
)
async def publicar_vacante(
    vacante_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:publicar", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        vacante = await _service(session).publicar(vacante_id, _empresa(current_user, empresa_id))
    except VacanteError as exc:
        _raise(exc)
    await _events(session).published(
        record_id=vacante.id,
        new_data={"titulo": vacante.titulo, "estado": vacante.estado},
        **_audit_context(http_request, current_user),
    )
    return vacante


@router.patch(
    "/{vacante_id}/reanudar",
    response_model=VacanteResponse,
    summary="Reanudar vacante",
    description="Reanuda una vacante pausada (PAUSADA -> PUBLICADA).",
)
async def reanudar_vacante(
    vacante_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:publicar", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        vacante = await _service(session).reanudar(vacante_id, _empresa(current_user, empresa_id))
    except VacanteError as exc:
        _raise(exc)
    await _events(session).resumed(
        record_id=vacante.id,
        new_data={"titulo": vacante.titulo, "estado": vacante.estado},
        **_audit_context(http_request, current_user),
    )
    return vacante


@router.patch(
    "/{vacante_id}/pausar",
    response_model=VacanteResponse,
    summary="Pausar vacante",
    description=(
        "Retira temporalmente del portal público una vacante publicada "
        "(PUBLICADA -> PAUSADA). Devuelve 409 si la vacante está en otro estado."
    ),
    responses={409: {"description": "La vacante no está publicada."}},
)
async def pausar_vacante(
    vacante_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:publicar", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        vacante = await _service(session).pausar(vacante_id, _empresa(current_user, empresa_id))
    except VacanteError as exc:
        _raise(exc)
    await _events(session).paused(
        record_id=vacante.id,
        new_data={"titulo": vacante.titulo, "estado": vacante.estado},
        **_audit_context(http_request, current_user),
    )
    return vacante


@router.patch(
    "/{vacante_id}/cerrar",
    response_model=VacanteResponse,
    summary="Cerrar vacante",
    description=(
        "Cierra el proceso de una vacante publicada o pausada "
        "(PUBLICADA|PAUSADA -> CERRADA). Devuelve 409 si la vacante está en otro estado."
    ),
    responses={409: {"description": "La vacante no está publicada ni pausada."}},
)
async def cerrar_vacante(
    vacante_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:publicar", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        vacante = await _service(session).cerrar(vacante_id, _empresa(current_user, empresa_id))
    except VacanteError as exc:
        _raise(exc)
    await _events(session).closed(
        record_id=vacante.id,
        new_data={"titulo": vacante.titulo, "estado": vacante.estado},
        **_audit_context(http_request, current_user),
    )
    return vacante


@router.delete(
    "/{vacante_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar vacante",
    description="Elimina una vacante que todavía no tiene publicaciones activas.",
)
async def eliminar_vacante(
    vacante_id: str,
    http_request: Request,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("vacantes:eliminar", "platform:vacantes:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        await _service(session).eliminar(vacante_id, _empresa(current_user, empresa_id))
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="La vacante tiene postulaciones") from exc
    except VacanteError as exc:
        _raise(exc)
    await _events(session).deleted(
        record_id=vacante_id,
        **_audit_context(http_request, current_user),
    )


@public_router.get(
    "/{empresa_slug}",
    response_model=EmpresaPublicaResponse,
    summary="Consultar información pública de empresa",
    description="Devuelve el perfil público de una empresa para su portal de empleo.",
)
async def obtener_empresa_publica(
    empresa_slug: str,
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import func, select

    from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel

    result = await session.execute(
        select(EmpresaModel).where(
            func.lower(EmpresaModel.slug) == empresa_slug.strip().lower(),
            EmpresaModel.activo.is_(True),
            EmpresaModel.eliminado_at.is_(None),
        )
    )
    empresa = result.scalar_one_or_none()
    if empresa is None or not getattr(empresa, "portal_publico_activo", True):
        raise HTTPException(status_code=404, detail="Empresa no encontrada o portal inactivo")
    return _to_empresa_publica(empresa)


def _to_empresa_publica(empresa) -> EmpresaPublicaResponse:
    """Serializa el perfil público usando las columnas reales de EmpresaModel."""
    return EmpresaPublicaResponse(
        id=str(empresa.id),
        nombre=empresa.razon_social,
        nombre_comercial=empresa.nombre_comercial,
        slug=empresa.slug,
        descripcion=empresa.descripcion,
        logo_url=empresa.logo_url,
        color_primario=empresa.color_primario or "#2563eb",
        portal_publico_activo=empresa.portal_publico_activo,
    )


@public_router.get(
    "/{empresa_slug}/vacantes",
    response_model=list[VacantePublicaResponse],
    summary="Listar vacantes públicas",
    description="Lista vacantes publicadas y vigentes de una empresa.",
)
async def listar_vacantes_publicas(
    empresa_slug: str,
    ubicacion: str | None = Query(default=None),
    modalidad: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    return await _service(session).listar_publicas(empresa_slug, ubicacion, modalidad)


@public_router.get(
    "/{empresa_slug}/vacantes/{vacante_id}",
    response_model=VacantePublicaResponse,
    summary="Consultar vacante pública",
    description="Obtiene el detalle público de una vacante vigente.",
)
async def obtener_vacante_publica(
    empresa_slug: str,
    vacante_id: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await _service(session).obtener_publica(empresa_slug, vacante_id)
    except VacanteNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Vacante no encontrada") from exc
