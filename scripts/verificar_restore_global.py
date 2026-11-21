"""Restaura en una base de prueba vacía y compara conteos de dos empresas.

Nunca acepta un destino con datos ni con nombre distinto de ssas_restore_*.
"""

import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from ssas.respaldos.infrastructure.services.postgres_tools import restore_dump


def counts(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='empresa_id' ORDER BY table_name")
        tables = [row[0] for row in cursor.fetchall()]
        by_table = {}
        for table in tables:
            from psycopg import sql
            cursor.execute(sql.SQL("SELECT empresa_id::text, count(*) FROM {} GROUP BY empresa_id ORDER BY empresa_id").format(sql.Identifier(table)))
            by_table[table] = dict(cursor.fetchall())
        employees = by_table["empleado"]
        cursor.execute("SELECT count(*) FROM contrato c JOIN empleado e ON e.id=c.empleado_id WHERE c.empresa_id<>e.empresa_id")
        cross_tenant = cursor.fetchone()[0]
    return {"empleados": employees, "por_tabla_y_empresa": by_table, "contratos_cruzados": cross_tenant}


def run():
    source = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    target = os.environ["TEST_RESTORE_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
    src = urlsplit(source)
    dst = urlsplit(target)
    if (src.hostname, src.port, src.path) == (dst.hostname, dst.port, dst.path):
        raise ValueError("El destino coincide con la base origen")
    if not dst.path.lstrip("/").startswith("ssas_restore_"):
        raise ValueError("El destino debe llamarse ssas_restore_*")
    dump = Path(os.environ["BACKUP_DUMP_PATH"]).resolve()
    manifest = json.loads(dump.with_suffix(".json").read_text(encoding="utf-8"))
    if hashlib.sha256(dump.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("El SHA-256 del dump no coincide")
    with psycopg.connect(target) as database, database.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
        if cursor.fetchone()[0]:
            raise ValueError("La base de prueba debe estar vacía")
    with psycopg.connect(source) as database:
        before = counts(database)
    if len(before["empleados"]) < 2:
        raise ValueError("Se necesitan al menos dos empresas con empleados en el origen")
    restore_dump(target, dump, os.getenv("PG_RESTORE_PATH", "pg_restore"))
    with psycopg.connect(target) as database:
        after = counts(database)
    if before != after or after["contratos_cruzados"]:
        raise AssertionError(f"La restauración no coincide: antes={before}; despues={after}")
    print(json.dumps({"estado": "VERIFICADO", "antes": before, "despues": after}, indent=2))


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:
        print(f"Verificación fallida: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
