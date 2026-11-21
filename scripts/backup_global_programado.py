"""Ejecutar desde un cron diario con DATABASE_URL y BACKUP_OUTPUT_DIRECTORY.

Cada ejecución escribe un dump custom de PostgreSQL, su SHA-256 y un manifiesto JSON.
El directorio debe ser un volumen persistente o un destino montado fuera del contenedor.
"""

import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ssas.respaldos.infrastructure.services.postgres_tools import create_dump


def run():
    database_url = os.environ["DATABASE_URL"]
    output = Path(os.environ["BACKUP_OUTPUT_DIRECTORY"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC)
    version = f"ssas-global-{stamp:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    partial = output / f".{version}.partial"
    destination = output / f"{version}.dump"
    try:
        create_dump(database_url, partial, os.getenv("PG_DUMP_PATH", "pg_dump"))
        if partial.stat().st_size == 0:
            raise RuntimeError("pg_dump generó un archivo vacío")
        digest = hashlib.sha256()
        with partial.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        partial.replace(destination)
        manifest = {
            "version": version, "created_at": stamp.isoformat(),
            "file": destination.name, "size_bytes": destination.stat().st_size,
            "sha256": digest.hexdigest(), "format": "pg_dump-custom-public",
        }
        (output / f"{version}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(json.dumps(manifest))
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Respaldo fallido: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
