"""Bandeja persistente y dispositivos del usuario autenticado."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.capacitacion.models import CursoModel, InscripcionModel
from ssas.capacitacion.router import local_today
from ssas.core.security.dependencies import CurrentUser, get_current_user
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import get_session
from ssas.personal.infrastructure.persistence.notification_models import (
    NotificacionDispositivoModel,
    NotificacionModel,
)
from ssas.personal.notification_service import notify

router = APIRouter(prefix="/notificaciones", tags=["Notificaciones"])


def require_company(user: CurrentUser) -> str:
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contraseña antes de continuar")
    if not user.empresa_id:
        raise HTTPException(403, "Selecciona una empresa")
    return user.empresa_id


def present(item: NotificacionModel) -> dict:
    return {"id": item.id, "tipo": item.tipo, "titulo": item.titulo,
            "mensaje": item.mensaje, "ruta": item.ruta, "fecha": item.fecha,
            "leida_en": item.leida_en}


@router.get("/mi")
async def my_notifications(user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    if not user.empresa_id:
        return []
    company = require_company(user)
    today = local_today()
    deadline = today + timedelta(days=7)
    due = (await session.execute(
        select(InscripcionModel, CursoModel.titulo)
        .join(EmpleadoModel, EmpleadoModel.id == InscripcionModel.empleado_id)
        .join(CursoModel, CursoModel.id == InscripcionModel.curso_id)
        .where(InscripcionModel.empresa_id == company, EmpleadoModel.empresa_id == company,
               EmpleadoModel.usuario_id == user.id, CursoModel.empresa_id == company,
               CursoModel.es_obligatorio.is_(True), InscripcionModel.estado.in_(("INSCRITO", "EN_CURSO")),
               InscripcionModel.fecha_limite.is_not(None), InscripcionModel.fecha_limite <= deadline,
               InscripcionModel.fecha_limite >= today)
    )).all()
    for enrollment, course_title in due:
        await notify(session, empresa_id=company, usuario_id=user.id,
            event_key=f"curso-vencer:{enrollment.id}:{enrollment.fecha_limite}",
            kind="CURSO_POR_VENCER", title="Curso obligatorio por vencer",
            message=f"{course_title} vence el {enrollment.fecha_limite:%d/%m/%Y}.",
            route=None)
    rows = await session.scalars(select(NotificacionModel).where(
        NotificacionModel.empresa_id == company, NotificacionModel.usuario_id == user.id,
    ).order_by(NotificacionModel.fecha.desc()).limit(100))
    return [present(row) for row in rows]


@router.patch("/{notification_id}/leer")
async def mark_read(notification_id: UUID, user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    company = require_company(user)
    row = await session.scalar(select(NotificacionModel).where(
        NotificacionModel.id == str(notification_id), NotificacionModel.empresa_id == company,
        NotificacionModel.usuario_id == user.id,
    ))
    if row is None:
        raise HTTPException(404, "Notificación no encontrada")
    row.leida_en = row.leida_en or datetime.now(UTC)
    return present(row)


@router.post("/leer-todas")
async def mark_all_read(user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    company = require_company(user)
    result = await session.execute(update(NotificacionModel).where(
        NotificacionModel.empresa_id == company, NotificacionModel.usuario_id == user.id,
        NotificacionModel.leida_en.is_(None),
    ).values(leida_en=datetime.now(UTC)))
    return {"actualizadas": result.rowcount}


class DeviceInput(BaseModel):
    token: str = Field(min_length=20, max_length=512)


@router.post("/dispositivos", status_code=201)
async def register_device(body: DeviceInput, user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    company = require_company(user)
    row = await session.scalar(select(NotificacionDispositivoModel).where(NotificacionDispositivoModel.token == body.token))
    if row is None:
        row = NotificacionDispositivoModel(id=str(uuid4()), empresa_id=company, usuario_id=user.id, token=body.token)
        session.add(row)
    else:
        row.empresa_id, row.usuario_id, row.actualizado_en = company, user.id, datetime.now(UTC)
    await session.flush()
    return {"registrado": True}


@router.delete("/dispositivos/{token}", status_code=204)
async def unregister_device(token: str, user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    company = require_company(user)
    row = await session.scalar(select(NotificacionDispositivoModel).where(
        NotificacionDispositivoModel.token == token, NotificacionDispositivoModel.usuario_id == user.id,
        NotificacionDispositivoModel.empresa_id == company,
    ))
    if row:
        await session.delete(row)
