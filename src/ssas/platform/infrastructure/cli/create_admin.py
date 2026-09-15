"""Crea el primer administrador de la plataforma.

Es el único usuario que no puede crearse por la API: cuando la base está vacía no hay
todavía nadie con permiso para hacerlo. A partir de él, el resto se crea por los
endpoints normales.

Un administrador de plataforma es una fila de ``usuario`` con ``empresa_id NULL``
y el rol global ``SUPER_ADMIN``. No hay tabla aparte.

    python -m ssas.platform.infrastructure.cli.create_admin \
        --nombre Ana --apellido Perez --email ana@ssas.bo --username ana
"""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import text

from ssas.auth.domain.exceptions import InvalidPasswordError
from ssas.auth.domain.password_policy import validate_password
from ssas.auth.infrastructure.security.password_hasher import Argon2PasswordHasher
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.infrastructure.database.session import AsyncSessionLocal

ROL_SUPER_ADMIN = "SUPER_ADMIN"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crea el primer superadministrador de SSAS")
    parser.add_argument("--nombre")
    parser.add_argument("--apellido")
    parser.add_argument("--email")
    parser.add_argument("--username")
    return parser


async def _create(args: argparse.Namespace, password: str) -> None:
    email = args.email.strip().lower()
    username = args.username.strip().lower()
    validate_password(password, email, username)

    async with AsyncSessionLocal() as session:
        existente = await session.execute(
            text(
                "SELECT id FROM usuario "
                "WHERE empresa_id IS NULL AND (lower(email) = :e OR lower(username) = :u)"
            ),
            {"e": email, "u": username},
        )
        if existente.scalar_one_or_none():
            raise ValueError("Ya existe un administrador de plataforma con ese email o username")

        rol_id = (
            await session.execute(
                text("SELECT id FROM rol WHERE empresa_id IS NULL AND codigo = :c"),
                {"c": ROL_SUPER_ADMIN},
            )
        ).scalar_one_or_none()
        if rol_id is None:
            raise ValueError(
                "No existe el rol global SUPER_ADMIN. Ejecutá antes 'alembic upgrade head'."
            )

        usuario_id = (
            await session.execute(
                text(
                    "INSERT INTO usuario "
                    "(empresa_id, nombres, apellidos, email, username, password_hash, "
                    " activo, email_verified, debe_cambiar_password) "
                    "VALUES (NULL, :nombre, :apellido, :email, :username, :hash, "
                    "        true, true, false) "
                    "RETURNING id"
                ),
                {
                    "nombre": args.nombre.strip(),
                    "apellido": args.apellido.strip(),
                    "email": email,
                    "username": username,
                    "hash": Argon2PasswordHasher().hash(password),
                },
            )
        ).scalar_one()

        await session.execute(
            text("INSERT INTO usuario_rol (usuario_id, rol_id) VALUES (:u, :r)"),
            {"u": usuario_id, "r": rol_id},
        )
        await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
            empresa_id=None,
            user_id=str(usuario_id),
            actor_label=email,
            module="AUTH_PLATFORM",
            action="BOOTSTRAP",
            description="Superadministrador inicial creado mediante CLI",
            affected_table="usuario",
            record_id=str(usuario_id),
        )
        await session.commit()
        print(f"Superadministrador creado: {email} ({usuario_id})")
        print("Iniciá sesión en POST /api/v1/auth/login SIN enviar empresa_slug.")


def main() -> None:
    args = _parser().parse_args()
    args.nombre = args.nombre or input("Nombre: ").strip()
    args.apellido = args.apellido or input("Apellido: ").strip()
    args.email = args.email or input("Email: ").strip()
    args.username = args.username or input("Username: ").strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirmar password: "):
        raise SystemExit("Las contraseñas no coinciden")
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(_create(args, password))
    except (InvalidPasswordError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
