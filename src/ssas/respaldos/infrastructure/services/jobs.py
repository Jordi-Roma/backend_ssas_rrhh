import asyncio
import hashlib
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.infrastructure.database.session import AsyncSessionLocal, engine
from ssas.respaldos.infrastructure.persistence.models.respaldo import RespaldoModel
from ssas.respaldos.infrastructure.services.postgres_tools import create_dump, restore_dump
from ssas.respaldos.infrastructure.services.storage import SupabaseBackupStorage


def storage() -> SupabaseBackupStorage:
    return SupabaseBackupStorage(
        settings.supabase_url,
        settings.supabase_service_role_key,
        settings.backup_storage_bucket,
    )


def _create_package(directory: Path, database_dump: Path) -> Path:
    package = directory / "ssas-rrhh.tar.gz"
    files_directory = Path(settings.backup_files_directory)
    with tarfile.open(package, "w:gz") as archive:
        archive.add(database_dump, arcname="database.dump")
        if files_directory.is_dir():
            archive.add(files_directory, arcname="files/cv")
    return package


def _extract_package(package: Path, destination: Path) -> Path:
    with tarfile.open(package, "r:gz") as archive:
        archive.extractall(destination, filter="data")
    database_dump = destination / "database.dump"
    if not database_dump.is_file():
        raise ValueError("El paquete no contiene database.dump")
    return database_dump


def _restore_files(extracted: Path) -> None:
    source = extracted / "files" / "cv"
    if not source.is_dir():
        return
    destination = Path(settings.backup_files_directory)
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)


def _event_user(respaldo: RespaldoModel, action: str) -> str:
    if action.startswith("BACKUP_RESTORE") and respaldo.restaurado_por_id:
        return respaldo.restaurado_por_id
    return respaldo.creado_por_id


async def _audit(session, respaldo: RespaldoModel, action: str, description: str) -> None:
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=None,
        module="BACKUP",
        action=action,
        description=description,
        user_id=_event_user(respaldo, action),
        affected_table="respaldo",
        record_id=respaldo.id,
        new_data={
            "nombre": respaldo.nombre,
            "estado": respaldo.estado,
            "sha256": respaldo.sha256,
            "tamano_bytes": respaldo.tamano_bytes,
        },
    )


async def create_backup_job(respaldo_id: str) -> None:
    async with AsyncSessionLocal() as session:
        respaldo = await session.get(RespaldoModel, respaldo_id)
        if respaldo is None:
            return
        respaldo.estado = "PROCESANDO"
        await session.commit()
        try:
            with tempfile.TemporaryDirectory(prefix="ssas-backup-") as directory:
                file_path = Path(directory) / f"{respaldo.id}.dump"
                await asyncio.to_thread(
                    create_dump, settings.database_url, file_path, settings.pg_dump_path
                )
                package = await asyncio.to_thread(_create_package, Path(directory), file_path)
                content = package.read_bytes()
                remote_path = f"system/{respaldo.fecha_creacion:%Y/%m}/{respaldo.id}.tar.gz"
                await asyncio.to_thread(storage().upload, remote_path, content)
                respaldo.ruta_storage = remote_path
                respaldo.tamano_bytes = len(content)
                respaldo.sha256 = hashlib.sha256(content).hexdigest()
                respaldo.estado = "COMPLETADO"
                respaldo.fecha_finalizacion = datetime.now(UTC)
                respaldo.mensaje_error = None
                await _audit(session, respaldo, "BACKUP_CREATE", "Respaldo completo generado")
        # El job debe persistir FALLIDO ante cualquier error externo de proceso, red o BD.
        except Exception as exc:  # noqa: BLE001
            respaldo.estado = "FALLIDO"
            respaldo.fecha_finalizacion = datetime.now(UTC)
            respaldo.mensaje_error = str(exc)[:2000]
            await _audit(session, respaldo, "BACKUP_CREATE_FAILED", "Falló la creación del respaldo")
        await session.commit()


async def restore_backup_job(respaldo_id: str, user_id: str) -> None:
    async with AsyncSessionLocal() as session:
        respaldo = await session.get(RespaldoModel, respaldo_id)
        if respaldo is None or not respaldo.ruta_storage:
            return
        respaldo.estado = "RESTAURANDO"
        respaldo.restaurado_por_id = user_id
        await session.commit()
        try:
            content = await asyncio.to_thread(storage().download, respaldo.ruta_storage)
            if hashlib.sha256(content).hexdigest() != respaldo.sha256:
                raise ValueError("El hash SHA-256 no coincide; restauración cancelada")
            with tempfile.TemporaryDirectory(prefix="ssas-restore-") as directory:
                file_path = Path(directory) / f"{respaldo.id}.tar.gz"
                file_path.write_bytes(content)
                extracted = Path(directory) / "extracted"
                extracted.mkdir()
                database_dump = await asyncio.to_thread(_extract_package, file_path, extracted)
                await engine.dispose()
                await asyncio.to_thread(
                    restore_dump, settings.database_url, database_dump, settings.pg_restore_path
                )
                await asyncio.to_thread(_restore_files, extracted)
            await session.rollback()
            restored = (
                await session.execute(select(RespaldoModel).where(RespaldoModel.id == respaldo_id))
            ).scalar_one_or_none()
            if restored is not None:
                restored.estado = "COMPLETADO"
                restored.fecha_restauracion = datetime.now(UTC)
                restored.restaurado_por_id = user_id
                restored.mensaje_error = None
                await _audit(session, restored, "BACKUP_RESTORE", "Base de datos restaurada")
        # Es la frontera del trabajo en segundo plano; el error se conserva para la UI.
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            failed = await session.get(RespaldoModel, respaldo_id)
            if failed is not None:
                failed.estado = "FALLIDO"
                failed.restaurado_por_id = user_id
                failed.mensaje_error = str(exc)[:2000]
                await _audit(session, failed, "BACKUP_RESTORE_FAILED", "Falló la restauración")
        await session.commit()
