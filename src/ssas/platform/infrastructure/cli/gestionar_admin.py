"""Inspección y mantenimiento de cuentas, sin tocar el esquema.

    python -m ssas.platform.infrastructure.cli.gestionar_admin --listar
    python -m ssas.platform.infrastructure.cli.gestionar_admin --buscar ja.guevara
    python -m ssas.platform.infrastructure.cli.gestionar_admin --cambiar-password --email x@y.bo
    python -m ssas.platform.infrastructure.cli.gestionar_admin --verificar-email --email x@y.bo

Ninguna operación borra datos. La contraseña se pide por consola y nunca se pasa
como argumento, para que no quede en el historial de la terminal.
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
from ssas.infrastructure.database.base import import_all_models
from ssas.infrastructure.database.session import AsyncSessionLocal

import_all_models()

CONSULTA_CUENTAS = """
SELECT u.email,
       u.username,
       COALESCE(e.slug, '(plataforma)')                AS ambito,
       u.activo,
       u.email_verified,
       u.debe_cambiar_password,
       u.bloqueado_hasta,
       COALESCE(string_agg(r.codigo, ', ' ORDER BY r.codigo), '(sin rol)') AS roles
FROM usuario u
LEFT JOIN empresa e     ON e.id = u.empresa_id
LEFT JOIN usuario_rol ur ON ur.usuario_id = u.id
LEFT JOIN rol r          ON r.id = ur.rol_id
{filtro}
GROUP BY u.id, u.email, u.username, e.slug, u.activo, u.email_verified,
         u.debe_cambiar_password, u.bloqueado_hasta
ORDER BY ambito, u.email
"""


async def _listar(patron: str | None) -> int:
    filtro = ""
    parametros: dict[str, str] = {}
    if patron:
        filtro = "WHERE u.email ILIKE :p OR u.username ILIKE :p"
        parametros["p"] = f"%{patron}%"

    async with AsyncSessionLocal() as session:
        filas = (
            await session.execute(text(CONSULTA_CUENTAS.format(filtro=filtro)), parametros)
        ).all()

    if not filas:
        print(
            "No se encontró ninguna cuenta" + (f" que coincida con '{patron}'." if patron else ".")
        )
        return 1

    print(f"\n{'CORREO':<34}{'USUARIO':<16}{'ÁMBITO':<14}{'ESTADO':<34}ROLES")
    print("─" * 128)
    for f in filas:
        estado = []
        estado.append("activo" if f.activo else "INACTIVO")
        if not f.email_verified:
            estado.append("SIN VERIFICAR")
        if f.debe_cambiar_password:
            estado.append("debe cambiar clave")
        if f.bloqueado_hasta:
            estado.append("BLOQUEADO")
        print(
            f"{f.email:<34}{(f.username or ''):<16}{f.ambito:<14}{', '.join(estado):<34}{f.roles}"
        )

    plataforma = sum(1 for f in filas if f.ambito == "(plataforma)")
    print(
        f"\n{len(filas)} cuenta(s): {plataforma} de plataforma, {len(filas) - plataforma} de empresa."
    )
    print("Las de plataforma inician sesión SIN empresa_slug; las de empresa, CON él.\n")
    return 0


async def _cambiar_password(email: str) -> int:
    email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        fila = (
            await session.execute(
                text(
                    "SELECT u.id, u.empresa_id, u.username, COALESCE(e.slug,'(plataforma)') AS ambito "
                    "FROM usuario u LEFT JOIN empresa e ON e.id = u.empresa_id "
                    "WHERE lower(u.email) = :e"
                ),
                {"e": email},
            )
        ).first()
        if fila is None:
            print(f"No existe ninguna cuenta con el correo {email}.", file=sys.stderr)
            print("Ejecutá --listar para ver las cuentas registradas.", file=sys.stderr)
            return 1

        print(f"Cuenta encontrada: {email} · usuario '{fila.username}' · ámbito {fila.ambito}")
        nueva = getpass.getpass("Nueva contraseña: ")
        if nueva != getpass.getpass("Confirmar contraseña: "):
            print("Las contraseñas no coinciden.", file=sys.stderr)
            return 1
        validate_password(nueva, email, fila.username or "")

        await session.execute(
            text(
                "UPDATE usuario SET password_hash = :h, debe_cambiar_password = false, "
                "intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = :id"
            ),
            {"h": Argon2PasswordHasher().hash(nueva), "id": fila.id},
        )
        # Cambiar la contraseña cierra todas las sesiones abiertas de esa cuenta.
        await session.execute(
            text(
                "UPDATE refresh_token SET revoked_at = now() "
                "WHERE usuario_id = :id AND revoked_at IS NULL"
            ),
            {"id": fila.id},
        )
        await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
            empresa_id=str(fila.empresa_id) if fila.empresa_id else None,
            user_id=str(fila.id),
            actor_label=email,
            module="AUTH",
            action="UPDATE",
            description="Contraseña restablecida por CLI",
            affected_table="usuario",
            record_id=str(fila.id),
        )
        await session.commit()

    print(f"Contraseña actualizada para {email}. Las sesiones anteriores quedaron revocadas.")
    return 0


async def _verificar_email(email: str) -> int:
    email = email.strip().lower()
    async with AsyncSessionLocal() as session:
        resultado = await session.execute(
            text("UPDATE usuario SET email_verified = true WHERE lower(email) = :e RETURNING id"),
            {"e": email},
        )
        if resultado.first() is None:
            print(f"No existe ninguna cuenta con el correo {email}.", file=sys.stderr)
            return 1
        await session.commit()
    print(f"Correo {email} marcado como verificado.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspecciona y mantiene cuentas de SSAS")
    parser.add_argument("--listar", action="store_true", help="lista todas las cuentas")
    parser.add_argument("--buscar", metavar="TEXTO", help="filtra por correo o usuario")
    parser.add_argument("--cambiar-password", action="store_true")
    parser.add_argument("--verificar-email", action="store_true")
    parser.add_argument("--email", help="correo de la cuenta a modificar")
    args = parser.parse_args()

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        if args.cambiar_password or args.verificar_email:
            if not args.email:
                print("Falta --email", file=sys.stderr)
                return 2
            accion = _cambiar_password if args.cambiar_password else _verificar_email
            return asyncio.run(accion(args.email))
        return asyncio.run(_listar(args.buscar))
    except InvalidPasswordError as exc:
        print(f"Contraseña rechazada: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
