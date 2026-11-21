"""Entrega FCM tras confirmar la transacción; la bandeja persiste aunque FCM falle."""

import asyncio
import json
import logging
import os
from threading import Lock

from sqlalchemy import select

from ssas.personal.infrastructure.persistence.notification_models import (
    NotificacionDispositivoModel,
    NotificacionModel,
)

logger = logging.getLogger(__name__)
_firebase_lock = Lock()


def _send(installation_id: str, title: str, body: str, route: str | None):
    import firebase_admin
    from firebase_admin import credentials, messaging

    with _firebase_lock:
        try:
            firebase_admin.get_app()
        except ValueError:
            raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")
            credential = credentials.Certificate(json.loads(raw)) if raw else credentials.ApplicationDefault()
            firebase_admin.initialize_app(credential)
    messaging.send(messaging.Message(
        fid=installation_id, notification=messaging.Notification(title=title, body=body),
        data={"ruta": route or "", "tipo": "SSAS"},
    ))


async def send_pending_push(session, notification_ids: list[str]):
    if not (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")):
        return
    try:
        rows = (await session.execute(
            select(NotificacionModel, NotificacionDispositivoModel.token)
            .join(NotificacionDispositivoModel,
                  (NotificacionDispositivoModel.usuario_id == NotificacionModel.usuario_id)
                  & (NotificacionDispositivoModel.empresa_id == NotificacionModel.empresa_id))
            .where(NotificacionModel.id.in_(notification_ids))
        )).all()
        capacity = asyncio.Semaphore(10)

        async def deliver(item, installation_id):
            try:
                async with capacity:
                    await asyncio.wait_for(
                        asyncio.to_thread(_send, installation_id, item.titulo, item.mensaje, item.ruta),
                        timeout=5,
                    )
            except Exception:
                logger.exception("No se pudo enviar notificación FCM %s", item.id)

        await asyncio.gather(*(deliver(item, token) for item, token in rows))
    except Exception:
        logger.exception("No se pudieron consultar los dispositivos FCM")
