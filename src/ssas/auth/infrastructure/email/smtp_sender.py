import asyncio
import smtplib
from email.message import EmailMessage

from ssas.auth.domain.exceptions import EmailDeliveryError
from ssas.auth.ports.outgoing.email_sender import EmailSender
from ssas.config.settings import settings


class SMTPEmailSender(EmailSender):
    async def send(self, recipient: str, subject: str, text: str, html: str) -> None:
        if not settings.smtp_host or not settings.smtp_from_email or not settings.smtp_only_email:
            raise EmailDeliveryError("El servicio SMTP no está configurado")
        await asyncio.to_thread(self._send_sync, recipient, subject, text, html)

    @staticmethod
    def _send_sync(recipient: str, subject: str, text: str, html: str) -> None:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        if not settings.smtp_only_email:
            raise EmailDeliveryError("El destinatario único no está configurado")
        message["To"] = settings.smtp_only_email
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError("No fue posible enviar el correo") from exc
