import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit


class PostgresToolError(RuntimeError):
    pass


def _connection(database_url: str) -> tuple[list[str], dict[str, str]]:
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    if not parsed.hostname or not parsed.username:
        raise PostgresToolError("DATABASE_URL no contiene una conexión PostgreSQL válida")
    args = [
        "--host", parsed.hostname,
        "--port", str(parsed.port or 5432),
        "--username", unquote(parsed.username),
        "--dbname", unquote(parsed.path.lstrip("/") or "postgres"),
    ]
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    env.setdefault("PGSSLMODE", "require")
    return args, env


def _executable(configured: str) -> str:
    resolved = shutil.which(configured)
    if resolved is None:
        raise PostgresToolError(
            f"No se encontró {configured}. Instala postgresql-client en el contenedor"
        )
    return resolved


def create_dump(database_url: str, destination: Path, pg_dump_path: str) -> None:
    connection, env = _connection(database_url)
    command = [
        _executable(pg_dump_path), *connection,
        "--format=custom", "--compress=9", "--no-owner", "--no-privileges",
        "--schema=public", "--file", str(destination),
    ]
    _run(command, env, "No se pudo generar el respaldo")


def restore_dump(database_url: str, source: Path, pg_restore_path: str) -> None:
    connection, env = _connection(database_url)
    command = [
        _executable(pg_restore_path), *connection,
        "--clean", "--if-exists", "--no-owner", "--no-privileges",
        "--single-transaction", str(source),
    ]
    _run(command, env, "No se pudo restaurar el respaldo")


def _run(command: list[str], env: dict[str, str], message: str) -> None:
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=1800, check=False
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2000:]
        raise PostgresToolError(f"{message}: {detail}")
