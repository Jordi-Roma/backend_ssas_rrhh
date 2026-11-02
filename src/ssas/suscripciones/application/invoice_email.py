"""Entrega de comprobantes de pagos confirmados mediante Resend."""

import re
from base64 import b64encode
from html import escape
from urllib.parse import urlparse

import httpx

from ssas.config.settings import settings
from ssas.suscripciones.application.payment_receipt import create_payment_receipt


class InvoiceEmailError(Exception):
    pass


def paid_invoice_message(invoice: dict, recipient: str) -> dict:
    if not settings.smtp_only_email:
        raise InvoiceEmailError("El destinatario único no está configurado")
    if invoice.get("status") != "paid" or not invoice.get("id"):
        raise InvoiceEmailError("La factura no está pagada")
    url = invoice.get("hosted_invoice_url") or invoice.get("invoice_pdf")
    parsed = urlparse(url or "")
    if url and (parsed.scheme != "https" or not parsed.hostname or not (
        parsed.hostname == "stripe.com" or parsed.hostname.endswith(".stripe.com")
    )):
        raise InvoiceEmailError("La factura no tiene un enlace oficial de Stripe")
    number = invoice.get("number") or invoice["id"]
    try:
        receipt = create_payment_receipt(invoice, recipient)
    except (ValueError, OverflowError, KeyError) as exc:
        raise InvoiceEmailError("No se pudo generar el comprobante de pago") from exc
    subject = f"Comprobante de pago SSAS RRHH {number}"
    text = "Tu pago de SSAS RRHH fue confirmado. Adjuntamos el comprobante en PDF."
    html = "<p>Tu pago de SSAS RRHH fue confirmado.</p><p>Adjuntamos tu comprobante de pago en PDF.</p>"
    if url:
        text += f"\nConsulta la factura de Stripe: {url}"
        html += f'<p><a href="{escape(url, quote=True)}">Consultar factura de Stripe</a></p>'
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", str(invoice["id"]))[:80]
    message = {
        "from": f"{settings.smtp_from_name} <{settings.smtp_from_email}>",
        "to": [settings.smtp_only_email], "subject": subject, "text": text, "html": html,
        "attachments": [{"filename": f"comprobante-{safe_id}.pdf", "content": b64encode(receipt).decode("ascii")}],
    }
    return message


async def send_paid_invoice(invoice: dict, recipient: str) -> None:
    """Usa el ID de la factura para deduplicar reintentos del webhook."""
    if settings.smtp_host != "smtp.resend.com" or not settings.smtp_password or not settings.smtp_from_email or not settings.smtp_only_email:
        raise InvoiceEmailError("Configura Resend para enviar comprobantes")
    message = paid_invoice_message(invoice, recipient)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.smtp_password}",
                    "Idempotency-Key": f"stripe-invoice-{invoice['id']}",
                },
                json=message,
            )
        response.raise_for_status()
    except (httpx.HTTPError, ValueError) as exc:
        raise InvoiceEmailError("Resend no pudo aceptar el correo de comprobante") from exc
