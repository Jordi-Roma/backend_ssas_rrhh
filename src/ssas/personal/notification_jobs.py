"""Revisa cursos obligatorios próximos a vencer y envía sus avisos."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select

from ssas.capacitacion.models import CursoModel, InscripcionModel
from ssas.capacitacion.router import local_today
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import AsyncSessionLocal
from ssas.personal.notification_service import notify
from ssas.personal.push_service import send_pending_push

logger = logging.getLogger(__name__)


async def generate_due_course_notifications() -> int:
    today = local_today()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(InscripcionModel, CursoModel.titulo, EmpleadoModel.usuario_id)
            .join(CursoModel, (CursoModel.id == InscripcionModel.curso_id)
                  & (CursoModel.empresa_id == InscripcionModel.empresa_id))
            .join(EmpleadoModel, (EmpleadoModel.id == InscripcionModel.empleado_id)
                  & (EmpleadoModel.empresa_id == InscripcionModel.empresa_id))
            .where(CursoModel.es_obligatorio.is_(True), InscripcionModel.estado.in_(("INSCRITO", "EN_CURSO")),
                   InscripcionModel.fecha_limite.between(today, today + timedelta(days=7)),
                   EmpleadoModel.usuario_id.is_not(None))
        )).all()
        created = 0
        for enrollment, title, recipient in rows:
            item = await notify(session, empresa_id=enrollment.empresa_id, usuario_id=recipient,
                event_key=f"curso-vencer:{enrollment.id}:{enrollment.fecha_limite}",
                kind="CURSO_POR_VENCER", title="Curso obligatorio por vencer",
                message=f"{title} vence el {enrollment.fecha_limite:%d/%m/%Y}.",
                route=None)
            created += bool(item)
        await session.commit()
        await send_pending_push(session, session.info.pop("notifications_to_push", []))
        return created


async def notification_worker():
    while True:
        try:
            await generate_due_course_notifications()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("No se pudieron revisar los cursos próximos a vencer")
        await asyncio.sleep(3600)
