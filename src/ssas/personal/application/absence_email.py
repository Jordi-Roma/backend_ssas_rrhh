"""Avisos de ausencias enviados después de guardar la operación."""

import logging
from html import escape

from ssas.auth.domain.exceptions import EmailDeliveryError
from ssas.auth.infrastructure.email.smtp_sender import SMTPEmailSender
from ssas.config.settings import settings

logger = logging.getLogger(__name__)


async def send_absence_notice(_recipients: list[str], subject: str, message: str, path: str) -> None:
    """El fallo del correo no revierte una solicitud ya confirmada."""
    if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_only_email:
        logger.warning("Aviso de ausencia omitido: SMTP sin configurar")
        return
    url = f"{settings.app_frontend_url.rstrip('/')}/{path.lstrip('/')}"
    text = f"{message}\n\nConsulta el detalle en {url}"
    html = f'<p>{escape(message)}</p><p><a href="{escape(url, quote=True)}">Ver en SSAS RRHH</a></p>'
    sender = SMTPEmailSender()
    try:
        await sender.send(settings.smtp_only_email, subject, text, html)
    except EmailDeliveryError:
        logger.exception("No se pudo enviar un aviso de ausencia")
