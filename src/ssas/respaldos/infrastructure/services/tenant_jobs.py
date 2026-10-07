import asyncio
import hashlib
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.session import AsyncSessionLocal
from ssas.respaldos.infrastructure.persistence.models.respaldo_empresa import RespaldoEmpresaModel
from ssas.respaldos.infrastructure.persistence.models.respaldo_empresa_config import (
    RespaldoEmpresaConfigModel,
)
from ssas.respaldos.infrastructure.services.errors import TenantBackupError
from ssas.respaldos.infrastructure.services.r2_storage import R2BackupStorage
from ssas.respaldos.infrastructure.services.tenant_package import create_tenant_package

logger = logging.getLogger(__name__)


def _failure_detail(exc: Exception, stage: str) -> str:
    if isinstance(exc, TenantBackupError):
        return f"{stage}: {exc}"
    return f"{stage}: {type(exc).__name__}"


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _audit(session, job: RespaldoEmpresaModel, action: str) -> None:
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=job.empresa_id,
        module="BACKUP",
        action=action,
        description="Respaldo por empresa",
        user_id=job.creado_por_id,
        affected_table="respaldo_empresa",
        record_id=job.id,
        new_data={"origen": job.origen, "estado": job.estado, "sha256": job.sha256},
    )


async def enqueue_backup(empresa_id: str, origen: str, actor_id: str | None) -> RespaldoEmpresaModel:
    if not settings.tenant_backup_enabled:
        raise RuntimeError("Los respaldos por empresa todavía no están habilitados")
    try:
        async with AsyncSessionLocal() as session:
            company = await session.get(EmpresaModel, empresa_id)
            if company is None or company.eliminado_at is not None or not company.activo:
                raise ValueError("Empresa no disponible")
            pending = await session.scalar(
                select(RespaldoEmpresaModel.id).where(
                    RespaldoEmpresaModel.empresa_id == empresa_id,
                    RespaldoEmpresaModel.estado.in_(("PENDIENTE", "PROCESANDO")),
                )
            )
            if pending:
                raise ValueError("Ya hay un respaldo de esta empresa en curso")
            job = RespaldoEmpresaModel(
                id=str(uuid4()), empresa_id=empresa_id, origen=origen,
                estado="PENDIENTE", creado_por_id=actor_id, fecha_creacion=datetime.now(UTC),
            )
            session.add(job)
            await _audit(session, job, "BACKUP_TENANT_REQUESTED")
            await session.commit()
            return job
    except IntegrityError as exc:
        raise ValueError("Ya hay un respaldo de esta empresa en curso") from exc


async def schedule_daily_backups() -> int:
    if not settings.tenant_backup_enabled:
        raise RuntimeError("TENANT_BACKUP_ENABLED debe ser true para el Cron")
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    queued = 0
    async with AsyncSessionLocal() as session:
        company_ids = (await session.execute(
            select(EmpresaModel.id).outerjoin(
                RespaldoEmpresaConfigModel,
                RespaldoEmpresaConfigModel.empresa_id == EmpresaModel.id,
            ).where(
                EmpresaModel.activo.is_(True), EmpresaModel.eliminado_at.is_(None),
                or_(
                    RespaldoEmpresaConfigModel.empresa_id.is_(None),
                    RespaldoEmpresaConfigModel.auto_habilitado.is_(True),
                ),
            )
        )).scalars().all()
    for empresa_id in company_ids:
        async with AsyncSessionLocal() as session:
            previous = await session.scalar(
                select(RespaldoEmpresaModel.id).where(
                    RespaldoEmpresaModel.empresa_id == empresa_id,
                    RespaldoEmpresaModel.origen == "AUTO",
                    RespaldoEmpresaModel.fecha_creacion >= start,
                    RespaldoEmpresaModel.estado.in_(("PENDIENTE", "PROCESANDO", "COMPLETADO")),
                ).limit(1)
            )
        if previous:
            continue
        try:
            await enqueue_backup(empresa_id, "AUTO", None)
            queued += 1
        except ValueError:
            continue  # Ya hay trabajo en curso o la empresa cambió de estado.
    return queued


async def _claim() -> str | None:
    async with AsyncSessionLocal() as session, session.begin():
        # Una ejecución interrumpida puede volver a intentarse al recuperar el servicio.
        await session.execute(
            update(RespaldoEmpresaModel)
            .where(
                RespaldoEmpresaModel.estado == "PROCESANDO",
                RespaldoEmpresaModel.fecha_inicio < datetime.now(UTC) - timedelta(hours=6),
            )
            .values(estado="PENDIENTE", fecha_inicio=None)
        )
        job = await session.scalar(
            select(RespaldoEmpresaModel)
            .where(RespaldoEmpresaModel.estado == "PENDIENTE")
            .order_by(RespaldoEmpresaModel.fecha_creacion)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.estado = "PROCESANDO"
        job.fecha_inicio = datetime.now(UTC)
        job.intentos += 1
        return job.id


async def _process(job_id: str) -> None:
    async with AsyncSessionLocal() as session:
        job = await session.get(RespaldoEmpresaModel, job_id)
        if job is None:
            return
        empresa_id, origen, created = job.empresa_id, job.origen, job.fecha_creacion
    key = f"tenant-{origen.lower()}/{empresa_id}/{created:%Y/%m/%d}/{job_id}.tar.gz"
    stage = "empaquetado"
    try:
        with tempfile.TemporaryDirectory(prefix="ssas-tenant-backup-") as directory:
            package = Path(directory) / f"{job_id}.tar.gz"
            await create_tenant_package(package, empresa_id)
            checksum = await asyncio.to_thread(_checksum, package)
            size = package.stat().st_size
            stage = "subida R2"
            await asyncio.to_thread(R2BackupStorage().upload, package, key)
        stage = "registro"
        async with AsyncSessionLocal() as session:
            job = await session.get(RespaldoEmpresaModel, job_id)
            if job is None:
                return
            job.ruta_storage = key
            job.sha256 = checksum
            job.tamano_bytes = size
            job.estado = "COMPLETADO"
            job.fecha_finalizacion = datetime.now(UTC)
            job.mensaje_error = None
            await _audit(session, job, "BACKUP_TENANT_COMPLETED")
            await session.commit()
    except Exception as exc:  # noqa: BLE001 - la frontera del worker registra fallos externos.
        detail = _failure_detail(exc, stage)
        logger.warning("Respaldo %s falló: %s", job_id, detail)
        async with AsyncSessionLocal() as session:
            job = await session.get(RespaldoEmpresaModel, job_id)
            if job is None:
                return
            job.estado = "PENDIENTE" if job.intentos < 3 else "FALLIDO"
            job.fecha_finalizacion = datetime.now(UTC) if job.estado == "FALLIDO" else None
            job.mensaje_error = detail
            await _audit(session, job, "BACKUP_TENANT_FAILED")
            await session.commit()
        if job.estado == "PENDIENTE":
            await asyncio.sleep(5)


async def expire_old_backups() -> None:
    cutoff = datetime.now(UTC) - timedelta(days=settings.tenant_backup_retention_days)
    async with AsyncSessionLocal() as session:
        old = (await session.execute(
            select(RespaldoEmpresaModel).where(
                RespaldoEmpresaModel.origen == "AUTO",
                RespaldoEmpresaModel.estado == "COMPLETADO",
                RespaldoEmpresaModel.fecha_creacion < cutoff,
            ).order_by(RespaldoEmpresaModel.fecha_creacion)
        )).scalars().all()
        for job in old:
            newer = await session.scalar(select(RespaldoEmpresaModel.id).where(
                RespaldoEmpresaModel.empresa_id == job.empresa_id,
                RespaldoEmpresaModel.estado == "COMPLETADO",
                RespaldoEmpresaModel.fecha_creacion > job.fecha_creacion,
            ).limit(1))
            if newer is None or not job.ruta_storage:
                continue  # Preservar la última copia disponible.
            await asyncio.to_thread(R2BackupStorage().delete, job.ruta_storage)
            job.estado = "EXPIRADO"
            job.ruta_storage = None
            await _audit(session, job, "BACKUP_TENANT_EXPIRED")
            await session.commit()


async def backup_worker() -> None:
    cleanup_at = datetime.now(UTC)
    while True:
        try:
            job_id = await _claim()
            if job_id:
                await _process(job_id)
                continue
            if datetime.now(UTC) >= cleanup_at:
                await expire_old_backups()
                cleanup_at = datetime.now(UTC) + timedelta(hours=1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - el worker se recupera de fallos externos.
            logger.error("Ciclo de backup interrumpido: %s", type(exc).__name__)
        await asyncio.sleep(5)
