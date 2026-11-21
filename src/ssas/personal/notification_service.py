"""Crea eventos de bandeja de forma idempotente dentro de la transacción de negocio."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.personal.infrastructure.persistence.notification_models import NotificacionModel
from ssas.roles.infrastructure.persistence.models.role import RoleModel
from ssas.roles.infrastructure.persistence.models.user_role import usuario_rol_table


async def notify(session: AsyncSession, *, empresa_id: str, usuario_id: str | None,
                 event_key: str, kind: str, title: str, message: str, route: str | None = None):
    if not usuario_id:
        return None
    notification_id = str(uuid4())
    created = await session.scalar(
        insert(NotificacionModel).values(
            id=notification_id, empresa_id=empresa_id, usuario_id=usuario_id,
            evento_clave=event_key, tipo=kind, titulo=title, mensaje=message, ruta=route,
        ).on_conflict_do_nothing(constraint="uq_notificacion_evento_usuario")
        .returning(NotificacionModel.id)
    )
    if created:
        session.info.setdefault("notifications_to_push", []).append(notification_id)
    return created


async def notify_roles(session: AsyncSession, *, empresa_id: str, roles: tuple[str, ...],
                       event_key: str, kind: str, title: str, message: str, route: str):
    recipients = (await session.scalars(
        select(UserModel.id)
        .join(usuario_rol_table, usuario_rol_table.c.usuario_id == UserModel.id)
        .join(RoleModel, RoleModel.id == usuario_rol_table.c.rol_id)
        .where(UserModel.empresa_id == empresa_id, UserModel.is_active.is_(True),
               UserModel.eliminado_at.is_(None), RoleModel.empresa_id == empresa_id,
               RoleModel.codigo.in_(roles), RoleModel.is_active.is_(True))
        .distinct()
    )).all()
    for recipient in recipients:
        await notify(session, empresa_id=empresa_id, usuario_id=recipient,
                     event_key=event_key, kind=kind, title=title, message=message, route=route)
