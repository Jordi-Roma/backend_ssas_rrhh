"""Public interview access with an application tracking code."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.api.request_metadata import get_client_ip
from ssas.entrevistas.infrastructure.persistence.models.entrevista import EntrevistaModel
from ssas.infrastructure.database.session import get_session
from ssas.postulaciones.infrastructure.persistence.models.postulacion import PostulacionModel
from ssas.postulantes.infrastructure.persistence.models.postulante import PostulanteModel

router = APIRouter(prefix="/publico/postulaciones", tags=["Portal público"])


class EntrevistaVisible(BaseModel):
    id: str
    fecha_hora: datetime
    duracion_min: int
    modalidad: str
    lugar: str | None
    enlace_reunion: str | None
    estado: str


async def _postulacion(session: AsyncSession, codigo: str, lock: bool = False):
    query = (
        select(PostulacionModel, PostulanteModel.empresa_id)
        .join(PostulanteModel, PostulanteModel.id == PostulacionModel.postulante_id)
        .where(PostulacionModel.codigo_seguimiento == codigo)
    )
    if lock:
        query = query.with_for_update(of=PostulacionModel)
    return (await session.execute(query)).one_or_none()


async def _entrevista(
    session: AsyncSession, postulacion_id: str,
    entrevista_id: str | None = None, lock: bool = False,
):
    query = select(EntrevistaModel).where(
        EntrevistaModel.postulacion_id == postulacion_id,
        EntrevistaModel.estado.in_(("PROGRAMADA", "CONFIRMADA")),
        EntrevistaModel.fecha_hora > datetime.now(UTC),
    )
    if entrevista_id:
        query = query.where(EntrevistaModel.id == entrevista_id)
    query = query.order_by(EntrevistaModel.fecha_hora, EntrevistaModel.id)
    if lock:
        query = query.with_for_update(of=EntrevistaModel)
    return await session.scalar(query)


def _visible(item: EntrevistaModel) -> EntrevistaVisible:
    return EntrevistaVisible(
        id=item.id, fecha_hora=item.fecha_hora, duracion_min=item.duracion_min,
        modalidad=item.modalidad, lugar=item.lugar,
        enlace_reunion=item.enlace_reunion, estado=item.estado,
    )


@router.get(
    "/{codigo}/entrevista",
    response_model=EntrevistaVisible,
    description="Consulta la próxima entrevista activa mediante el código de seguimiento.",
)
async def consultar_entrevista(codigo: str, session: AsyncSession = Depends(get_session)):
    row = await _postulacion(session, codigo)
    if row is None or row[0].estado != "ACTIVA":
        raise HTTPException(404, "No hay entrevista disponible.")
    item = await _entrevista(session, row[0].id)
    if item is None:
        raise HTTPException(404, "No hay entrevista disponible.")
    return _visible(item)


@router.post(
    "/{codigo}/entrevista/confirmar",
    response_model=EntrevistaVisible,
    description="Confirma la entrevista programada mediante el código de seguimiento.",
)
async def confirmar_entrevista(
    codigo: str, entrevista_id: UUID, request: Request,
    session: AsyncSession = Depends(get_session),
):
    row = await _postulacion(session, codigo, lock=True)
    if row is None:
        raise HTTPException(404, "No hay entrevista disponible.")
    if row[0].estado != "ACTIVA":
        raise HTTPException(409, "La postulación ya no está activa.")
    item = await _entrevista(session, row[0].id, str(entrevista_id), lock=True)
    if item is None or item.estado != "PROGRAMADA":
        raise HTTPException(409, "Esta entrevista ya no se puede confirmar.")
    item.estado = "CONFIRMADA"
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=row[1], module="SELECCION", action="UPDATE",
        description="Entrevista confirmada con código de seguimiento",
        actor_label="Postulante con código de seguimiento", affected_table="entrevista",
        record_id=item.id, source_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        new_data={"estado": "CONFIRMADA"},
    )
    return _visible(item)
