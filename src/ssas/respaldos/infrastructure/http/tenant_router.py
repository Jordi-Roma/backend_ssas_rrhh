import asyncio
import hashlib
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.api.openapi import TAG_RESPALDOS_EMPRESA
from ssas.core.security.dependencies import (
    CurrentUser,
    require_platform_permission,
    require_scoped_permission,
)
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.session import get_session
from ssas.respaldos.infrastructure.persistence.models.respaldo_empresa import RespaldoEmpresaModel
from ssas.respaldos.infrastructure.persistence.models.respaldo_empresa_config import (
    RespaldoEmpresaConfigModel,
)
from ssas.respaldos.infrastructure.services.r2_storage import R2BackupStorage
from ssas.respaldos.infrastructure.services.tenant_jobs import enqueue_backup
from ssas.suscripciones.infrastructure.http.feature_guard import (
    has_plan_feature,
    require_plan_feature,
)

router = APIRouter(prefix="/respaldos-empresa", tags=[TAG_RESPALDOS_EMPRESA])


class TenantBackupRequest(BaseModel):
    empresa_id: str | None = None


class TenantBackupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    empresa_id: str
    origen: str
    estado: str
    fecha_creacion: datetime
    fecha_inicio: datetime | None
    fecha_finalizacion: datetime | None
    tamano_bytes: int | None
    sha256: str | None
    mensaje_error: str | None


class LatestBackupsResponse(BaseModel):
    ultimo_intento: TenantBackupResponse | None
    ultimo_exitoso: TenantBackupResponse | None


class BackupConfigResponse(BaseModel):
    empresa_id: str
    auto_habilitado: bool
    hora_local: str
    zona_horaria: str
    hora_configurable: bool
    retencion_dias: int
    servicio_habilitado: bool


class BackupConfigRequest(BaseModel):
    auto_habilitado: bool | None = None
    hora_local: str | None = Field(default=None, pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

    @model_validator(mode="after")
    def require_change(self) -> "BackupConfigRequest":
        if self.auto_habilitado is None and self.hora_local is None:
            raise ValueError("Indica auto_habilitado u hora_local")
        return self


def _scope(user: CurrentUser, empresa_id: str | None) -> str | None:
    if user.es_plataforma:
        return empresa_id
    if empresa_id is not None and empresa_id != user.empresa_id:
        raise HTTPException(status_code=403, detail="No puedes consultar otra empresa")
    return user.empresa_id


@router.get("/configuracion/{empresa_id}", response_model=BackupConfigResponse)
async def get_tenant_backup_config(
    empresa_id: str,
    _user: CurrentUser = Depends(require_platform_permission("platform:backup:ver")),
    session: AsyncSession = Depends(get_session),
):
    """Consulta si la copia diaria está habilitada para la empresa indicada."""
    if await session.get(EmpresaModel, empresa_id) is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    config = await session.get(RespaldoEmpresaConfigModel, empresa_id)
    custom_time = await has_plan_feature(session, empresa_id, "horario_respaldo")
    return BackupConfigResponse(
        empresa_id=empresa_id,
        auto_habilitado=config.auto_habilitado if config else True,
        hora_local=(config.hora_local if config else "02:00") if custom_time else "02:00",
        zona_horaria="America/La_Paz",
        hora_configurable=custom_time,
        retencion_dias=settings.tenant_backup_retention_days,
        servicio_habilitado=settings.tenant_backup_enabled,
    )


@router.patch("/configuracion/{empresa_id}", response_model=BackupConfigResponse)
async def update_tenant_backup_config(
    empresa_id: str,
    request: BackupConfigRequest,
    user: CurrentUser = Depends(require_platform_permission("platform:backup:configurar")),
    session: AsyncSession = Depends(get_session),
):
    """Configura la copia diaria y su hora de Bolivia desde plataforma."""
    if await session.get(EmpresaModel, empresa_id) is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if request.hora_local is not None:
        await require_plan_feature(session, empresa_id, "horario_respaldo")
    config = await session.get(RespaldoEmpresaConfigModel, empresa_id)
    if config is None:
        config = RespaldoEmpresaConfigModel(
            empresa_id=empresa_id, auto_habilitado=True, hora_local="02:00"
        )
        session.add(config)
    if request.auto_habilitado is not None:
        config.auto_habilitado = request.auto_habilitado
    if request.hora_local is not None:
        config.hora_local = request.hora_local
    config.actualizado_en = datetime.now(UTC)
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=empresa_id, module="BACKUP", action="BACKUP_TENANT_CONFIG_CHANGED",
        description="Programación automática modificada", user_id=user.id,
        affected_table="respaldo_empresa_config", record_id=empresa_id,
        new_data={"auto_habilitado": config.auto_habilitado, "hora_local": config.hora_local},
    )
    custom_time = await has_plan_feature(session, empresa_id, "horario_respaldo")
    return BackupConfigResponse(
        empresa_id=empresa_id,
        auto_habilitado=config.auto_habilitado,
        hora_local=config.hora_local if custom_time else "02:00",
        zona_horaria="America/La_Paz",
        hora_configurable=custom_time,
        retencion_dias=settings.tenant_backup_retention_days,
        servicio_habilitado=settings.tenant_backup_enabled,
    )


async def _get_owned(session: AsyncSession, backup_id: str, user: CurrentUser) -> RespaldoEmpresaModel:
    backup = await session.get(RespaldoEmpresaModel, backup_id)
    if backup is None or (not user.es_plataforma and backup.empresa_id != user.empresa_id):
        raise HTTPException(status_code=404, detail="Respaldo no encontrado")
    return backup


@router.get("", response_model=list[TenantBackupResponse], summary="Listar respaldos por empresa")
async def list_tenant_backups(
    empresa_id: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(require_scoped_permission("backup:ver", "platform:backup:ver")),
    session: AsyncSession = Depends(get_session),
):
    """Lista el historial paginado del alcance autorizado; plataforma puede ver todas."""
    scope = _scope(user, empresa_id)
    query = select(RespaldoEmpresaModel).order_by(
        RespaldoEmpresaModel.fecha_creacion.desc(), RespaldoEmpresaModel.id.desc()
    ).limit(limit).offset(offset)
    if scope is not None:
        query = query.where(RespaldoEmpresaModel.empresa_id == scope)
    return (await session.execute(query)).scalars().all()


@router.get("/ultimo", response_model=LatestBackupsResponse, summary="Último respaldo de empresa")
async def latest_tenant_backup(
    empresa_id: str | None = Query(default=None),
    user: CurrentUser = Depends(require_scoped_permission("backup:ver", "platform:backup:ver")),
    session: AsyncSession = Depends(get_session),
):
    """Devuelve el último intento y la última copia válida de una empresa."""
    scope = _scope(user, empresa_id)
    if scope is None:
        raise HTTPException(status_code=422, detail="Selecciona una empresa")
    base = select(RespaldoEmpresaModel).where(RespaldoEmpresaModel.empresa_id == scope)
    ultimo = await session.scalar(base.order_by(RespaldoEmpresaModel.fecha_creacion.desc()).limit(1))
    exitoso = await session.scalar(
        base.where(RespaldoEmpresaModel.estado == "COMPLETADO")
        .order_by(RespaldoEmpresaModel.fecha_creacion.desc()).limit(1)
    )
    return LatestBackupsResponse(
        ultimo_intento=TenantBackupResponse.model_validate(ultimo) if ultimo else None,
        ultimo_exitoso=TenantBackupResponse.model_validate(exitoso) if exitoso else None,
    )


@router.post("", response_model=TenantBackupResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_tenant_backup(
    request: TenantBackupRequest,
    user: CurrentUser = Depends(require_scoped_permission("backup:crear", "platform:backup:crear")),
):
    """Solicita una copia manual; el backend con el volumen de CV la procesa."""
    scope = _scope(user, request.empresa_id)
    if scope is None:
        raise HTTPException(status_code=422, detail="Selecciona una empresa")
    try:
        return await enqueue_backup(scope, "MANUAL", user.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{backup_id}", response_model=TenantBackupResponse)
async def get_tenant_backup(
    backup_id: str,
    user: CurrentUser = Depends(require_scoped_permission("backup:ver", "platform:backup:ver")),
    session: AsyncSession = Depends(get_session),
):
    """Consulta el estado de una copia sin revelar copias de otras empresas."""
    return await _get_owned(session, backup_id, user)


@router.get("/{backup_id}/descargar", summary="Descargar respaldo de empresa")
async def download_tenant_backup(
    backup_id: str,
    user: CurrentUser = Depends(require_scoped_permission("backup:descargar", "platform:backup:descargar")),
    session: AsyncSession = Depends(get_session),
):
    """Descarga una copia completa tras comprobar su integridad SHA-256."""
    backup = await _get_owned(session, backup_id, user)
    if backup.estado != "COMPLETADO" or not backup.ruta_storage or not backup.sha256:
        raise HTTPException(status_code=409, detail="El respaldo no está disponible")
    if not backup.ruta_storage.startswith(
        f"tenant-{backup.origen.lower()}/{backup.empresa_id}/"
    ):
        raise HTTPException(status_code=409, detail="Ruta de respaldo inválida")
    with tempfile.NamedTemporaryFile(prefix="ssas-download-", suffix=".tar.gz", delete=False) as file:
        path = Path(file.name)
    try:
        await asyncio.to_thread(R2BackupStorage().download, backup.ruta_storage, path)
        def checksum() -> str:
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()
        if await asyncio.to_thread(checksum) != backup.sha256:
            raise HTTPException(status_code=409, detail="El respaldo no superó la verificación SHA-256")
        await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
            empresa_id=backup.empresa_id, module="BACKUP", action="BACKUP_TENANT_DOWNLOAD",
            description="Respaldo de empresa descargado", user_id=user.id,
            affected_table="respaldo_empresa", record_id=backup.id,
        )
        return FileResponse(
            path, media_type="application/octet-stream",
            filename=f"ssas-empresa-{backup.fecha_creacion:%Y%m%d}-{backup.id}.tar.gz",
            background=BackgroundTask(path.unlink, missing_ok=True),
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
