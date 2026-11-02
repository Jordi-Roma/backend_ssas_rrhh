"""Validación cerrada de paquetes para restauración por empresa.

La restauración solo acepta el formato generado por tenant_package; nunca extrae
rutas del tar ni ejecuta SQL contenido en el paquete.
"""

import asyncio
import base64
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

from sqlalchemy import Date, DateTime, Numeric, delete, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.config.settings import settings
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.base import Base
from ssas.infrastructure.database.session import AsyncSessionLocal
from ssas.respaldos.infrastructure.persistence.models.respaldo_empresa import RespaldoEmpresaModel
from ssas.respaldos.infrastructure.services.errors import TenantBackupError
from ssas.respaldos.infrastructure.services.r2_storage import R2BackupStorage
from ssas.respaldos.infrastructure.services.tenant_package import (
    CHILD_TABLES,
    DIRECT_TABLES,
    FORMAT_VERSION,
    _check_table_inventory,
    create_tenant_package,
)

TABLE_NAMES = set(DIRECT_TABLES) | {name for name, _, _ in CHILD_TABLES}
IMMUTABLE_TABLES = {"bitacora"}


@dataclass
class ValidatedPackage:
    manifest: dict[str, Any]
    rows: dict[str, list[dict[str, Any]]]
    files: dict[str, bytes]


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"__base64__"}:
            return base64.b64decode(value["__base64__"], validate=True)
        if set(value) == {"__decimal__"}:
            return Decimal(value["__decimal__"])
        return {key: _decode(item) for key, item in value.items()}
    return value


def _typed_row(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    table = Base.metadata.tables[name]
    if not isinstance(raw, dict) or set(raw) != set(table.c.keys()):
        raise TenantBackupError(f"Columnas inesperadas en {name}")
    row = {}
    for column in table.c:
        value = _decode(raw[column.name])
        if value is not None and isinstance(column.type, DateTime):
            value = datetime.fromisoformat(value)
        elif value is not None and isinstance(column.type, Date):
            value = date.fromisoformat(value)
        elif value is not None and isinstance(column.type, Numeric):
            value = Decimal(str(value))
        row[column.name] = value
    return row


def read_tenant_package(path: Path, empresa_id: str, schema_revision: str) -> ValidatedPackage:
    _check_table_inventory()
    try:
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or any(
                not member.isfile() or member.issym() or member.islnk()
                or PurePosixPath(member.name).is_absolute()
                or ".." in PurePosixPath(member.name).parts
                for member in members
            ):
                raise TenantBackupError("El paquete contiene entradas inválidas")
            manifest = json.load(archive.extractfile("manifest.json"))
            if (
                manifest.get("format_version") != FORMAT_VERSION
                or manifest.get("empresa_id") != empresa_id
                or manifest.get("schema_revision") != schema_revision
            ):
                raise TenantBackupError("Empresa, formato o versión de esquema incompatibles")
            data = archive.extractfile("data.json").read()
            if hashlib.sha256(data).hexdigest() != manifest.get("data_sha256"):
                raise TenantBackupError("Los datos del paquete no superaron SHA-256")
            raw_rows = json.loads(data)
            if not isinstance(raw_rows, dict) or set(raw_rows) != TABLE_NAMES:
                raise TenantBackupError("Tablas faltantes o inesperadas en el paquete")
            if not isinstance(manifest.get("rows"), dict) or set(manifest["rows"]) != TABLE_NAMES:
                raise TenantBackupError("Conteos de tablas incompletos")
            rows = {}
            for name in TABLE_NAMES:
                if not isinstance(raw_rows[name], list) or manifest["rows"].get(name) != len(raw_rows[name]):
                    raise TenantBackupError(f"Conteo inválido para {name}")
                rows[name] = [_typed_row(name, raw) for raw in raw_rows[name]]
                if name in DIRECT_TABLES and any(str(row["empresa_id"]) != empresa_id for row in rows[name]):
                    raise TenantBackupError(f"Fila de otra empresa en {name}")
            owned = {name: {str(row["id"]) for row in table_rows if "id" in row}
                     for name, table_rows in rows.items()}
            for name, fk_name, parent in CHILD_TABLES:
                if any(str(row[fk_name]) not in owned[parent] for row in rows[name]):
                    raise TenantBackupError(f"Referencia ajena en {name}")
            for name, table_rows in rows.items():
                for fk in Base.metadata.tables[name].foreign_keys:
                    parent = fk.column.table.name
                    if parent not in TABLE_NAMES or parent == "usuario":
                        continue
                    if any(row[fk.parent.name] is not None and str(row[fk.parent.name]) not in owned[parent]
                           for row in table_rows):
                        raise TenantBackupError(f"Referencia fuera de la empresa en {name}")
            files = {}
            listed = manifest.get("files")
            if not isinstance(listed, list):
                raise TenantBackupError("Manifiesto de archivos inválido")
            for entry in listed:
                member_name = entry["path"]
                if member_name in files or not member_name.startswith(("files/cv/", "files/employee-documents/")):
                    raise TenantBackupError("Archivo duplicado o fuera del paquete")
                content = archive.extractfile(member_name).read()
                if len(content) != entry["size"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise TenantBackupError("Archivo sin integridad")
                files[member_name] = content
            if set(names) != {"manifest.json", "data.json", *files}:
                raise TenantBackupError("El paquete contiene archivos no declarados")
            return ValidatedPackage(manifest, rows, files)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as exc:
        raise TenantBackupError("Paquete de respaldo inválido") from exc


def table_order() -> list[str]:
    dependencies = {
        name: {fk.column.table.name for fk in Base.metadata.tables[name].foreign_keys
               if fk.column.table.name in TABLE_NAMES and fk.column.table.name != name}
        for name in TABLE_NAMES
    }
    remaining = set(TABLE_NAMES)
    ordered: list[str] = []
    while remaining:
        ready = sorted(name for name in remaining if not dependencies[name] & remaining)
        if not ready:
            raise TenantBackupError("Dependencias circulares entre tablas del respaldo")
        ordered.extend(ready)
        remaining.difference_update(ready)
    return ordered


def file_targets(package: ValidatedPackage, empresa_id: str) -> dict[Path, bytes]:
    cv_root = Path(settings.cv_storage_directory).resolve()
    document_root = (Path(settings.employee_files_directory).resolve() / empresa_id)
    postulantes = {row["cv_url"] for row in package.rows["postulante"] if row.get("cv_url")}
    documents = {str(row["id"]): row for row in package.rows["documento_empleado"]}
    targets: dict[Path, bytes] = {}
    seen_cv: set[str] = set()
    seen_documents: set[str] = set()
    for entry in package.manifest["files"]:
        content = package.files[entry["path"]]
        if "cv_url" in entry:
            cv_url = entry["cv_url"]
            if cv_url not in postulantes or cv_url in seen_cv:
                raise TenantBackupError("CV sin referencia única en la empresa")
            seen_cv.add(cv_url)
            filename = Path(cv_url).name
            target = (cv_root / filename).resolve()
            if not target.is_relative_to(cv_root) or target.suffix.lower() not in {".pdf", ".docx"}:
                raise TenantBackupError("Ruta de CV inválida")
        elif "documento_id" in entry:
            doc_id = str(entry["documento_id"])
            if doc_id not in documents or doc_id in seen_documents:
                raise TenantBackupError("Documento sin referencia única en la empresa")
            seen_documents.add(doc_id)
            target = Path(documents[doc_id]["ruta_privada"]).resolve()
            if not target.is_relative_to(document_root):
                raise TenantBackupError("Ruta de documento fuera de la empresa")
        else:
            raise TenantBackupError("Archivo sin referencia")
        if target in targets:
            raise TenantBackupError("Dos archivos usan la misma ruta")
        targets[target] = content
    if seen_cv != postulantes or seen_documents != set(documents):
        raise TenantBackupError("Faltan archivos de la empresa en el paquete")
    return targets


async def replace_tenant_rows(session: AsyncSession, empresa_id: str, package: ValidatedPackage) -> None:
    """Sustituye filas tenant en la transacción del llamador; no toca tablas globales."""
    order = [name for name in table_order() if name not in IMMUTABLE_TABLES]
    current_ids: dict[str, set[str]] = {}
    for name in order:
        table = Base.metadata.tables[name]
        if name in DIRECT_TABLES:
            query = select(table.c.id).where(table.c.empresa_id == empresa_id)
        else:
            fk_name, parent = next((fk, parent) for child, fk, parent in CHILD_TABLES if child == name)
            if "id" not in table.c:
                current_ids[name] = set()
                continue
            query = select(table.c.id).where(table.c[fk_name].in_(current_ids[parent]))
        current_ids[name] = set((await session.scalars(query)).all())
    # Las referencias recursivas RESTRICT impiden el borrado masivo hasta quedar en NULL.
    for name in ("contrato", "departamento"):
        table = Base.metadata.tables[name]
        for fk in table.foreign_keys:
            if fk.column.table.name == name:
                await session.execute(update(table).where(table.c.id.in_(current_ids[name])).values({fk.parent.name: None}))
    for name in reversed(order):
        table = Base.metadata.tables[name]
        if name == "usuario":
            restored = {str(row["id"]) for row in package.rows[name]}
            removed = {str(value) for value in current_ids[name]} - restored
            audit = Base.metadata.tables["bitacora"]
            audited = {str(value) for value in (await session.scalars(
                select(audit.c.usuario_id).where(audit.c.usuario_id.in_(removed))
            )).all()}
            if audited:
                raise TenantBackupError(
                    "Hay usuarios posteriores al respaldo vinculados a la bitácora inmutable"
                )
            if removed:
                await session.execute(delete(table).where(table.c.id.in_(removed)))
            continue
        if current_ids[name]:
            await session.execute(delete(table).where(table.c.id.in_(current_ids[name])))
        elif "id" not in table.c:
            fk_name, parent = next((fk, parent) for child, fk, parent in CHILD_TABLES if child == name)
            if current_ids[parent]:
                await session.execute(delete(table).where(table.c[fk_name].in_(current_ids[parent])))
    self_references = []
    for name in order:
        table = Base.metadata.tables[name]
        rows = package.rows[name]
        self_columns = [fk.parent.name for fk in table.foreign_keys if fk.column.table.name == name]
        if rows:
            inserts = [{**row, **{key: None for key in self_columns}} for row in rows]
            if name == "usuario":
                for row in inserts:
                    statement = pg_insert(table).values(**row)
                    await session.execute(statement.on_conflict_do_update(
                        index_elements=[table.c.id],
                        set_={key: value for key, value in row.items() if key != "id"},
                        where=table.c.empresa_id == empresa_id,
                    ))
            else:
                await session.execute(table.insert(), inserts)
            for row in rows:
                if any(row[key] is not None for key in self_columns):
                    self_references.append((table, row, self_columns))
    for table, row, columns in self_references:
        await session.execute(update(table).where(table.c.id == row["id"]).values(
            {key: row[key] for key in columns}
        ))


def install_files(targets: dict[Path, bytes]) -> tuple[ExitStack, list[tuple[Path, Path | None]]]:
    """Instala archivos conservando copias locales para revertir si falla la BD."""
    stack = ExitStack()
    changes: list[tuple[Path, Path | None]] = []
    try:
        for target, content in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            directory = Path(stack.enter_context(tempfile.TemporaryDirectory(dir=target.parent, prefix=".restore-")))
            previous = directory / "previous" if target.exists() else None
            if previous:
                shutil.copy2(target, previous)
            replacement = directory / "replacement"
            replacement.write_bytes(content)
            os.replace(replacement, target)
            changes.append((target, previous))
        return stack, changes
    except Exception:
        undo_files(changes)
        stack.close()
        raise


def undo_files(changes: list[tuple[Path, Path | None]]) -> None:
    for target, previous in reversed(changes):
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            os.replace(previous, target)


async def schema_revision() -> str:
    async with AsyncSessionLocal() as session:
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    if not revision:
        raise TenantBackupError("No se pudo identificar la versión del esquema")
    return revision


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def download_and_validate(backup: RespaldoEmpresaModel, target: Path) -> ValidatedPackage:
    if backup.estado != "COMPLETADO" or not backup.sha256 or not backup.ruta_storage:
        raise TenantBackupError("El respaldo no está completo")
    if not backup.ruta_storage.startswith(f"tenant-{backup.origen.lower()}/{backup.empresa_id}/"):
        raise TenantBackupError("Ruta de respaldo inválida")
    await asyncio.to_thread(R2BackupStorage().download, backup.ruta_storage, target)
    if await asyncio.to_thread(file_sha256, target) != backup.sha256:
        raise TenantBackupError("El respaldo no superó la verificación SHA-256")
    revision = await schema_revision()
    package = await asyncio.to_thread(read_tenant_package, target, backup.empresa_id, revision)
    await asyncio.to_thread(file_targets, package, backup.empresa_id)
    return package


async def create_safety_backup(empresa_id: str, actor_id: str) -> str:
    """Guarda un punto de retorno completo en R2 antes de alterar la empresa."""
    backup_id = str(uuid4())
    now = datetime.now(UTC)
    key = f"tenant-manual/{empresa_id}/{now:%Y/%m/%d}/{backup_id}.tar.gz"
    with tempfile.TemporaryDirectory(prefix="ssas-pre-restore-") as directory:
        path = Path(directory) / "safety.tar.gz"
        await create_tenant_package(path, empresa_id)
        checksum = await asyncio.to_thread(file_sha256, path)
        size = path.stat().st_size
        await asyncio.to_thread(R2BackupStorage().upload, path, key)
    async with AsyncSessionLocal() as session, session.begin():
        session.add(RespaldoEmpresaModel(
            id=backup_id, empresa_id=empresa_id, origen="MANUAL", estado="COMPLETADO",
            creado_por_id=actor_id, fecha_creacion=now, fecha_inicio=now,
            fecha_finalizacion=datetime.now(UTC), ruta_storage=key, sha256=checksum,
            tamano_bytes=size, intentos=1,
        ))
    return backup_id


async def restore_company(package: ValidatedPackage, empresa_id: str, actor_id: str) -> None:
    targets = await asyncio.to_thread(file_targets, package, empresa_id)
    stack = None
    changes = []
    try:
        async with AsyncSessionLocal() as session, session.begin():
            company = await session.scalar(
                select(EmpresaModel).where(EmpresaModel.id == empresa_id).with_for_update()
            )
            if company is None or company.eliminado_at is not None:
                raise TenantBackupError("Empresa no disponible")
            active = await session.scalar(select(RespaldoEmpresaModel.id).where(
                RespaldoEmpresaModel.empresa_id == empresa_id,
                RespaldoEmpresaModel.estado.in_(("PENDIENTE", "PROCESANDO")),
            ).limit(1))
            if active:
                raise TenantBackupError("Hay un respaldo de esta empresa en curso")
            postulante = Base.metadata.tables["postulante"]
            other_urls = (await session.scalars(select(postulante.c.cv_url).where(
                postulante.c.empresa_id != empresa_id, postulante.c.cv_url.is_not(None),
            ))).all()
            other_names = {Path(url).name for url in other_urls}
            if any(path.name in other_names for path in targets if path.is_relative_to(Path(settings.cv_storage_directory).resolve())):
                raise TenantBackupError("Un CV también es usado por otra empresa")
            usuario = Base.metadata.tables["usuario"]
            restored_users = {str(row["id"]) for row in package.rows["usuario"]}
            conflicting_users = (await session.scalars(select(usuario.c.id).where(
                usuario.c.id.in_(restored_users),
                or_(usuario.c.empresa_id != empresa_id, usuario.c.empresa_id.is_(None)),
            ))).first()
            if conflicting_users:
                raise TenantBackupError("Un usuario del paquete pertenece a otra empresa")
            external_users = {
                str(row[fk.parent.name])
                for name, table_rows in package.rows.items()
                for fk in Base.metadata.tables[name].foreign_keys
                if fk.column.table.name == "usuario"
                for row in table_rows
                if row[fk.parent.name] is not None and str(row[fk.parent.name]) not in restored_users
            }
            if external_users:
                global_users = set((await session.scalars(select(usuario.c.id).where(
                    usuario.c.id.in_(external_users), usuario.c.empresa_id.is_(None),
                ))).all())
                if external_users != global_users:
                    raise TenantBackupError("El paquete referencia usuarios de otra empresa")
            stack, changes = await asyncio.to_thread(install_files, targets)
            await replace_tenant_rows(session, empresa_id, package)
            # El actor es global y permanece fuera de las filas reemplazadas.
            from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
            from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
                SqlAlchemyAuditLogRepository,
            )
            await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
                empresa_id=empresa_id, module="BACKUP", action="BACKUP_TENANT_RESTORED",
                description="Empresa restaurada desde respaldo", user_id=actor_id,
                affected_table="empresa", record_id=empresa_id,
            )
    except Exception:
        if changes:
            await asyncio.to_thread(undo_files, changes)
        raise
    finally:
        if stack:
            stack.close()
