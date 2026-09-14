from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.events.postulacion_events import PostulacionEvents
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.api.openapi import TAG_PORTAL_PUBLICO
from ssas.core.api.request_metadata import get_client_ip
from ssas.infrastructure.database.session import get_session
from ssas.postulaciones.application.use_cases.consultar_postulacion_publica import (
    ConsultarPostulacionPublica,
)
from ssas.postulaciones.application.use_cases.crear_postulacion_publica import (
    CrearPostulacionPublica,
)
from ssas.postulaciones.domain.entities.postulacion_publica import (
    CvAdjunto,
    DatosPostulantePublico,
)
from ssas.postulaciones.domain.exceptions import (
    CvInvalidoError,
    EtapaInicialNoConfiguradaError,
    PostulacionDuplicadaError,
    PostulacionError,
    PostulacionNotFoundError,
    VacanteNoDisponibleError,
)
from ssas.postulaciones.infrastructure.http.schemas import (
    PostulacionPublicaResponse,
    SeguimientoPostulacionResponse,
)
from ssas.postulaciones.infrastructure.persistence.repositories.postulacion_publica_repository import (
    SqlAlchemyPostulacionPublicaRepository,
)
from ssas.postulaciones.infrastructure.storage.local_cv_storage import LocalCvStorage
from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel

NivelEducativo = Literal["SECUNDARIA", "TECNICO", "LICENCIATURA", "MAESTRIA", "DOCTORADO"]

router = APIRouter(prefix="/publico/postulaciones", tags=[TAG_PORTAL_PUBLICO])


def _repository(session: AsyncSession) -> SqlAlchemyPostulacionPublicaRepository:
    return SqlAlchemyPostulacionPublicaRepository(session)


def _events(session: AsyncSession) -> PostulacionEvents:
    repository = SqlAlchemyAuditLogRepository(session)
    return PostulacionEvents(RegisterAuditEvent(repository))


def _raise_http_postulacion_error(exc: PostulacionError) -> None:
    if isinstance(exc, PostulacionNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(exc, PostulacionDuplicadaError):
        code = status.HTTP_409_CONFLICT
    elif isinstance(exc, (CvInvalidoError, EtapaInicialNoConfiguradaError)):
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif isinstance(exc, VacanteNoDisponibleError):
        code = status.HTTP_404_NOT_FOUND
    else:
        code = status.HTTP_400_BAD_REQUEST
    raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.post(
    "",
    response_model=PostulacionPublicaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar postulacion publica",
    description=(
        "Recibe un formulario publico multipart con datos del postulante y CV. "
        "Crea o actualiza el postulante por empresa, crea la postulacion y devuelve "
        "un codigo de seguimiento."
    ),
    responses={
        404: {"description": "La vacante no existe o no esta publicada."},
        409: {"description": "El postulante ya postulo a esta vacante."},
        422: {"description": "Datos invalidos, CV invalido o etapa inicial no configurada."},
    },
)
async def crear_postulacion_publica(
    vacante_id: Annotated[str, Form(min_length=1)],
    nombres: Annotated[str, Form(min_length=1, max_length=120)],
    apellidos: Annotated[str, Form(min_length=1, max_length=120)],
    ci: Annotated[str, Form(min_length=1, max_length=30)],
    email: Annotated[EmailStr, Form()],
    telefono: Annotated[str, Form(min_length=1, max_length=40)],
    ciudad: Annotated[str, Form(min_length=1, max_length=100)],
    nivel_educativo: Annotated[NivelEducativo, Form()],
    anios_experiencia: Annotated[int, Form(ge=0)],
    cv: Annotated[UploadFile, File(description="Archivo CV en PDF o DOCX, maximo 5 MB.")],
    linkedin: Annotated[str | None, Form()] = None,
    http_request: Request = None,
    session: AsyncSession = Depends(get_session),
) -> PostulacionPublicaResponse:
    try:
        cv_content = await cv.read()
        result = await CrearPostulacionPublica(
            _repository(session),
            LocalCvStorage(),
        ).execute(
            DatosPostulantePublico(
                vacante_id=vacante_id,
                nombres=nombres.strip(),
                apellidos=apellidos.strip(),
                ci=ci.strip(),
                email=str(email),
                telefono=telefono.strip(),
                ciudad=ciudad.strip(),
                nivel_educativo=nivel_educativo,
                anios_experiencia=anios_experiencia,
                linkedin=linkedin.strip() if linkedin else None,
            ),
            CvAdjunto(
                filename=cv.filename or "",
                content_type=cv.content_type,
                content=cv_content,
            ),
        )
        empresa_id = await session.scalar(
            select(VacanteModel.empresa_id).where(VacanteModel.id == vacante_id)
        )
        await _events(session).publica_creada(
            empresa_id=empresa_id,
            record_id=result.id,
            new_data={
                "codigo_seguimiento": result.codigo_seguimiento,
                "vacante_id": vacante_id,
                "email": str(email),
            },
            actor_label=f"{nombres.strip()} {apellidos.strip()}",
            source_ip=get_client_ip(http_request) if http_request is not None else None,
            user_agent=(
                http_request.headers.get("user-agent") if http_request is not None else None
            ),
        )
        return PostulacionPublicaResponse(
            id=result.id,
            codigo_seguimiento=result.codigo_seguimiento,
            estado=result.estado,
            fecha_postulacion=result.fecha_postulacion,
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una postulacion para esta vacante",
        ) from exc
    except PostulacionError as exc:
        _raise_http_postulacion_error(exc)


@router.get(
    "/{codigo}",
    response_model=SeguimientoPostulacionResponse,
    summary="Consultar postulacion publica",
    description="Consulta el estado de una postulacion publica mediante su codigo de seguimiento.",
    responses={404: {"description": "No existe una postulacion con ese codigo."}},
)
async def consultar_postulacion_publica(
    codigo: str,
    session: AsyncSession = Depends(get_session),
) -> SeguimientoPostulacionResponse:
    try:
        result = await ConsultarPostulacionPublica(_repository(session)).execute(codigo)
        return SeguimientoPostulacionResponse(
            codigo_seguimiento=result.codigo_seguimiento,
            estado=result.estado,
            etapa=result.etapa,
            vacante=result.vacante,
            fecha_postulacion=result.fecha_postulacion,
            fecha_ultimo_cambio=result.fecha_ultimo_cambio,
        )
    except PostulacionError as exc:
        _raise_http_postulacion_error(exc)
