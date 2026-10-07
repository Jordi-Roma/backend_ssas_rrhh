"""Exportación lógica de filas pertenecientes a una empresa.

La lista cerrada falla si aparece una tabla tenant nueva sin clasificar. Esto evita
respaldos aparentemente correctos que omitan silenciosamente un módulo futuro.
"""

import base64
import hashlib
import io
import json
import shutil
import tarfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy import select, text

from ssas.config.settings import settings
from ssas.infrastructure.database.base import Base
from ssas.infrastructure.database.session import AsyncSessionLocal
from ssas.postulaciones.infrastructure.storage.local_cv_storage import LocalCvStorage

FORMAT_VERSION = 1
DIRECT_TABLES = (
    "usuario", "rol", "departamento", "cargo", "habilidad", "vacante",
    "postulante", "empleado", "etapa_reclutamiento", "motivo_rechazo",
    "conocimiento_articulo", "conocimiento_fragmento", "reporte_definicion",
    "reporte_ejecucion", "bitacora",
)
CHILD_TABLES = (
    ("usuario_rol", "usuario_id", "usuario"),
    ("rol_permiso", "rol_id", "rol"),
    ("vacante_habilidad", "vacante_id", "vacante"),
    ("postulante_habilidad", "postulante_id", "postulante"),
    ("postulacion", "vacante_id", "vacante"),
    ("postulacion_nota", "postulacion_id", "postulacion"),
    ("entrevista", "postulacion_id", "postulacion"),
    ("evaluacion", "postulacion_id", "postulacion"),
    ("analisis_cv", "postulacion_id", "postulacion"),
)
PLATFORM_TABLES = {
    "empresa_modulo", "suscripcion", "respaldo_empresa", "respaldo_empresa_config", "refresh_token",
    "password_reset_token", "email_verification_token",
}
GLOBAL_TABLES = {
    "empresa", "permiso", "modulo", "parametro_legal", "parametro_valor",
    "plan_suscripcion", "plan_modulo", "stripe_evento", "respaldo",
}


def _encode(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__base64__": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _encode(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _ids(rows: list[dict[str, Any]], column: str = "id") -> set[str]:
    return {str(row[column]) for row in rows}


def _check_table_inventory() -> None:
    known = set(DIRECT_TABLES) | {name for name, _, _ in CHILD_TABLES} | PLATFORM_TABLES | GLOBAL_TABLES
    unknown = sorted(set(Base.metadata.tables) - known)
    if unknown:
        raise RuntimeError(f"Tablas por empresa sin clasificar para backup: {', '.join(unknown)}")


async def _collect_rows(empresa_id: str) -> tuple[dict[str, list[dict[str, Any]]], str]:
    _check_table_inventory()
    result: dict[str, list[dict[str, Any]]] = {}
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        empresa = Base.metadata.tables["empresa"]
        if not (await session.execute(select(empresa.c.id).where(empresa.c.id == empresa_id))).first():
            raise ValueError("Empresa no encontrada")
        schema_revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        if not schema_revision:
            raise RuntimeError("No se pudo identificar la versión del esquema")
        for name in DIRECT_TABLES:
            table = Base.metadata.tables[name]
            rows = await session.execute(select(table).where(table.c.empresa_id == empresa_id))
            result[name] = [dict(row) for row in rows.mappings().all()]
        for name, fk_column, parent in CHILD_TABLES:
            table = Base.metadata.tables[name]
            parent_ids = _ids(result[parent])
            if not parent_ids:
                result[name] = []
                continue
            rows = await session.execute(select(table).where(table.c[fk_column].in_(parent_ids)))
            result[name] = [dict(row) for row in rows.mappings().all()]
        usuario = Base.metadata.tables["usuario"]
        global_users = {str(value) for value in (await session.execute(
            select(usuario.c.id).where(usuario.c.empresa_id.is_(None))
        )).scalars().all()}
        postulante = Base.metadata.tables["postulante"]
        other_cv_names = {
            Path(value).name for value in (await session.execute(
                select(postulante.c.cv_url).where(
                    postulante.c.empresa_id != empresa_id,
                    postulante.c.cv_url.is_not(None),
                )
            )).scalars().all()
        }

    owned = {name: _ids(rows) if rows and "id" in rows[0] else set() for name, rows in result.items()}
    for name, rows in result.items():
        table = Base.metadata.tables[name]
        for row in rows:
            for fk in table.foreign_keys:
                parent = fk.column.table.name
                value = row[fk.parent.name]
                if parent in owned and value is not None and str(value) not in owned[parent]:
                    if parent == "usuario" and str(value) in global_users:
                        continue  # Un actor global puede referenciar la empresa.
                    raise RuntimeError(f"Referencia ajena o ausente en {name}.{fk.parent.name}")
    for row in result["postulante"]:
        if row.get("cv_url") and Path(row["cv_url"]).name in other_cv_names:
            raise RuntimeError("Un CV tiene referencias en más de una empresa")
    return result, schema_revision


def _add_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mtime = int(datetime.now(UTC).timestamp())
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(content))


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_package(
    path: Path, empresa_id: str, rows: dict[str, list[dict[str, Any]]], schema_revision: str
) -> None:
    encoded = {
        name: [{key: _encode(value) for key, value in row.items()} for row in table_rows]
        for name, table_rows in rows.items()
    }
    content = json.dumps(encoded, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "schema_revision": schema_revision,
        "empresa_id": empresa_id,
        "created_at": datetime.now(UTC).isoformat(),
        "rows": {name: len(table_rows) for name, table_rows in rows.items()},
        "data_sha256": hashlib.sha256(content).hexdigest(),
        "files": [],
    }
    storage = LocalCvStorage(settings.cv_storage_directory)
    tracking_codes: dict[str, list[str]] = {}
    for application in rows["postulacion"]:
        tracking_codes.setdefault(str(application["postulante_id"]), []).append(
            application["codigo_seguimiento"]
        )
    files_seen: set[str] = set()
    with TemporaryDirectory(prefix="ssas-tenant-files-") as temporary:
        staged: list[tuple[Path, str]] = []
        for candidate in rows["postulante"]:
            cv_url = candidate.get("cv_url")
            if not cv_url or cv_url in files_seen:
                continue
            if not storage.owns_cv(cv_url, tracking_codes.get(str(candidate["id"]), [])):
                raise RuntimeError("Un CV no corresponde a las postulaciones de la empresa")
            source = storage.resolve_cv(cv_url)
            if source is None:
                raise RuntimeError("Un CV referenciado por la empresa no está disponible")
            files_seen.add(cv_url)
            arcname = f"files/cv/{hashlib.sha256(cv_url.encode()).hexdigest()}{source.suffix.lower()}"
            copy = Path(temporary) / Path(arcname).name
            # Una copia estable permite comparar el archivo antes/después de leerlo.
            before = _file_hash(source)
            with source.open("rb") as original, copy.open("wb") as staged_file:
                shutil.copyfileobj(original, staged_file, length=1024 * 1024)
            after = _file_hash(source)
            checksum = _file_hash(copy)
            if before != after or before != checksum:
                raise RuntimeError("Un CV cambió mientras se generaba el respaldo")
            manifest["files"].append({
                "cv_url": cv_url, "path": arcname, "sha256": checksum, "size": copy.stat().st_size,
            })
            staged.append((copy, arcname))
        with tarfile.open(path, "w:gz") as archive:
            _add_bytes(archive, "data.json", content)
            for source, arcname in staged:
                archive.add(source, arcname=arcname, recursive=False)
            _add_bytes(
                archive, "manifest.json",
                json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            )


async def create_tenant_package(path: Path, empresa_id: str) -> None:
    rows, schema_revision = await _collect_rows(empresa_id)
    # La compresión y lectura de archivos no bloquean el event loop de la API.
    import asyncio

    await asyncio.to_thread(_write_package, path, empresa_id, rows, schema_revision)
