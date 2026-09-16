import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.api.openapi import TAG_RESPALDOS
from ssas.core.security.dependencies import CurrentUser, require_platform_permission
from ssas.infrastructure.database.session import get_session
from ssas.respaldos.infrastructure.http.schemas import (
    CrearRespaldoSchema,
    OperacionRespaldoSchema,
    RespaldoSchema,
    RestaurarRespaldoSchema,
)
from ssas.respaldos.infrastructure.persistence.models.respaldo import RespaldoModel
from ssas.respaldos.infrastructure.services.jobs import (
    create_backup_job,
    restore_backup_job,
    storage,
)

router = APIRouter(prefix="/respaldos", tags=[TAG_RESPALDOS])


async def _get_completed(session: AsyncSession, respaldo_id: str) -> RespaldoModel:
    respaldo = await session.get(RespaldoModel, respaldo_id)
    if respaldo is None:
        raise HTTPException(status_code=404, detail="Respaldo no encontrado")
    if respaldo.estado != "COMPLETADO" or not respaldo.ruta_storage:
        raise HTTPException(status_code=409, detail="El respaldo todavía no está disponible")
    return respaldo


async def _audit(
    session: AsyncSession, respaldo: RespaldoModel, user_id: str, action: str, description: str
) -> None:
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=None,
        module="BACKUP",
        action=action,
        description=description,
        user_id=user_id,
        affected_table="respaldo",
        record_id=respaldo.id,
        new_data={"nombre": respaldo.nombre, "sha256": respaldo.sha256},
    )


@router.get(
    "",
    response_model=list[RespaldoSchema],
    summary="Listar respaldos",
    description="Lista hasta cien respaldos del sistema, ordenados desde el más reciente.",
)
async def list_backups(
    _user: CurrentUser = Depends(require_platform_permission("platform:backup:ver")),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(RespaldoModel).order_by(RespaldoModel.fecha_creacion.desc()).limit(100)
    )
    return result.scalars().all()


@router.post(
    "",
    response_model=OperacionRespaldoSchema,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Crear respaldo completo",
    description="Programa un volcado del esquema público y lo guarda en Storage privado.",
)
async def create_backup(
    request: CrearRespaldoSchema,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_platform_permission("platform:backup:crear")),
    session: AsyncSession = Depends(get_session),
):
    now = datetime.now(UTC)
    respaldo = RespaldoModel(
        id=str(uuid4()),
        nombre=(request.nombre or f"SSAS RRHH {now:%Y-%m-%d %H:%M UTC}").strip(),
        formato="tar.gz",
        estado="PENDIENTE",
        creado_por_id=user.id,
        fecha_creacion=now,
    )
    session.add(respaldo)
    await session.commit()
    background_tasks.add_task(create_backup_job, respaldo.id)
    return OperacionRespaldoSchema(
        id=respaldo.id, estado=respaldo.estado, mensaje="El respaldo comenzó a generarse"
    )


@router.get(
    "/{respaldo_id}/descargar",
    summary="Descargar respaldo",
    description="Verifica el hash SHA-256 antes de entregar el archivo de respaldo.",
)
async def download_backup(
    respaldo_id: str,
    user: CurrentUser = Depends(require_platform_permission("platform:backup:descargar")),
    session: AsyncSession = Depends(get_session),
):
    respaldo = await _get_completed(session, respaldo_id)
    content = await asyncio.to_thread(storage().download, respaldo.ruta_storage)
    if hashlib.sha256(content).hexdigest() != respaldo.sha256:
        raise HTTPException(status_code=409, detail="El respaldo no superó la verificación SHA-256")
    await _audit(session, respaldo, user.id, "BACKUP_DOWNLOAD", "Respaldo descargado")
    filename = f"ssas-rrhh-{respaldo.fecha_creacion:%Y%m%d-%H%M%S}.tar.gz"
    return Response(
        content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{respaldo_id}/restaurar",
    response_model=OperacionRespaldoSchema,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Restaurar toda la base de datos",
    description="Programa una restauración destructiva tras validar su habilitación y confirmación.",
)
async def restore_backup(
    respaldo_id: str,
    request: RestaurarRespaldoSchema,
    background_tasks: BackgroundTasks,
    user: CurrentUser = Depends(require_platform_permission("platform:backup:restaurar")),
    session: AsyncSession = Depends(get_session),
):
    if not settings.backup_restore_enabled:
        raise HTTPException(status_code=403, detail="La restauración está deshabilitada en este entorno")
    if request.confirmacion != settings.backup_restore_confirmation:
        raise HTTPException(status_code=422, detail="La frase de confirmación no coincide")
    respaldo = await _get_completed(session, respaldo_id)
    respaldo.estado = "RESTAURACION_PENDIENTE"
    respaldo.restaurado_por_id = user.id
    await session.commit()
    background_tasks.add_task(restore_backup_job, respaldo.id, user.id)
    return OperacionRespaldoSchema(
        id=respaldo.id,
        estado=respaldo.estado,
        mensaje="La restauración fue programada; no operes el sistema hasta que finalice",
    )


@router.delete(
    "/{respaldo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar respaldo",
    description="Elimina el archivo privado y su registro, salvo que exista una operación en curso.",
)
async def delete_backup(
    respaldo_id: str,
    user: CurrentUser = Depends(require_platform_permission("platform:backup:eliminar")),
    session: AsyncSession = Depends(get_session),
):
    respaldo = await session.get(RespaldoModel, respaldo_id)
    if respaldo is None:
        raise HTTPException(status_code=404, detail="Respaldo no encontrado")
    if respaldo.estado in {"PROCESANDO", "RESTAURANDO", "RESTAURACION_PENDIENTE"}:
        raise HTTPException(status_code=409, detail="No se puede eliminar una operación en curso")
    if respaldo.ruta_storage:
        await asyncio.to_thread(storage().delete, respaldo.ruta_storage)
    await _audit(session, respaldo, user.id, "BACKUP_DELETE", "Respaldo eliminado")
    await session.delete(respaldo)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
