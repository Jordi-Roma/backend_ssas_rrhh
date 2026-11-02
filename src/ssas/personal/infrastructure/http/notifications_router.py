"""Avisos personales derivados de operaciones confirmadas en la base."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.infrastructure.persistence.models.audit_log import AuditLogModel
from ssas.core.security.dependencies import CurrentUser, get_current_user
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import get_session
from ssas.personal.infrastructure.persistence.models import (
    ContratoModel,
    SolicitudAusenciaModel,
    TipoAusenciaModel,
)

router = APIRouter(prefix="/notificaciones", tags=["Personal"])


@router.get("/mi", summary="Consultar avisos de mi empresa")
async def my_notifications(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if user.must_change_password:
        raise HTTPException(403, "Debes cambiar tu contraseña antes de continuar")
    if not user.empresa_id:
        return []

    since = datetime.now(UTC) - timedelta(days=30)
    items: list[dict] = []
    worker_id = await session.scalar(
        select(EmpleadoModel.id).where(
            EmpleadoModel.empresa_id == user.empresa_id,
            EmpleadoModel.usuario_id == user.id,
        )
    )
    if worker_id:
        decisions = (await session.execute(
            select(SolicitudAusenciaModel, TipoAusenciaModel.nombre)
            .join(TipoAusenciaModel, TipoAusenciaModel.id == SolicitudAusenciaModel.tipo_ausencia_id)
            .where(
                SolicitudAusenciaModel.empresa_id == user.empresa_id,
                TipoAusenciaModel.empresa_id == user.empresa_id,
                SolicitudAusenciaModel.empleado_id == worker_id,
                SolicitudAusenciaModel.estado.in_(("APROBADA", "RECHAZADA")),
                SolicitudAusenciaModel.resuelto_en >= since,
            )
            .order_by(SolicitudAusenciaModel.resuelto_en.desc())
            .limit(30)
        )).all()
        for request, kind_name in decisions:
            items.append({
                "id": f"ausencia:{request.id}:{request.estado}",
                "tipo": "AUSENCIA_RESUELTA",
                "titulo": "Ausencia aprobada" if request.estado == "APROBADA" else "Ausencia rechazada",
                "mensaje": f"Tu solicitud de {kind_name} fue {request.estado.lower()}.",
                "fecha": request.resuelto_en,
            })


    if "JEFE_AREA" in user.roles or "RRHH" in user.roles or "ADMIN_EMPRESA" in user.roles:
        pending_query = select(SolicitudAusenciaModel).where(
            SolicitudAusenciaModel.empresa_id == user.empresa_id,
            SolicitudAusenciaModel.estado == "PENDIENTE",
            SolicitudAusenciaModel.creado_en >= since,
        )
        if "RRHH" not in user.roles and "ADMIN_EMPRESA" not in user.roles:
            if not worker_id:
                return sorted(items, key=lambda item: item["fecha"], reverse=True)[:50]
            team_ids = select(ContratoModel.empleado_id).where(
                ContratoModel.empresa_id == user.empresa_id,
                ContratoModel.jefe_directo_id == worker_id,
                ContratoModel.estado == "VIGENTE",
            )
            pending_query = pending_query.where(SolicitudAusenciaModel.empleado_id.in_(team_ids))
        pending = (await session.scalars(
            pending_query.order_by(SolicitudAusenciaModel.creado_en.desc()).limit(30)
        )).all()
        for request in pending:
            items.append({
                "id": f"ausencia-pendiente:{request.id}",
                "tipo": "AUSENCIA_PENDIENTE",
                "titulo": "Solicitud por revisar",
                "mensaje": "Hay una solicitud de ausencia pendiente de revisión.",
                "fecha": request.creado_en,
            })

    if "ADMIN_EMPRESA" in user.roles:
        events = (await session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.empresa_id == user.empresa_id,
                AuditLogModel.module == "SUSCRIPCION",
                AuditLogModel.action.in_(("SUBSCRIPTION_UPDATED", "SUBSCRIPTION_MANUAL_ADJUSTMENT")),
                AuditLogModel.fecha >= since,
            ).order_by(AuditLogModel.fecha.desc()).limit(30)
        )).all()
        for event in events:
            items.append({
                "id": f"suscripcion:{event.id}",
                "tipo": "SUSCRIPCION",
                "titulo": "Suscripción actualizada",
                "mensaje": "Se registró un cambio en el plan o su pago. Consulta Mi suscripción para ver el estado actual.",
                "fecha": event.fecha,
            })

    return sorted(items, key=lambda item: item["fecha"], reverse=True)[:50]
