from base64 import b64decode
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pypdf import PdfReader

from ssas.suscripciones.application import invoice_email
from ssas.suscripciones.application.invoice_email import InvoiceEmailError, paid_invoice_message
from ssas.suscripciones.infrastructure.http import router as subscriptions_router


def test_invoice_email_attaches_custom_receipt(monkeypatch):
    monkeypatch.setattr(invoice_email.settings, "smtp_only_email", "central@example.test")
    invoice = {"id": "in_123", "status": "paid", "invoice_pdf": "https://pay.stripe.com/invoice/pdf/123",
               "amount_paid": 4900, "currency": "usd", "created": 1790000000,
               "lines": {"data": [{"description": "Plan Profesional"}]}}
    message = paid_invoice_message(invoice, "billing@example.test")
    assert message["to"] == ["central@example.test"]
    assert "https://pay.stripe.com/invoice/pdf/123" in message["text"]
    assert message["attachments"][0]["filename"] == "comprobante-in_123.pdf"
    content = b64decode(message["attachments"][0]["content"])
    assert content.startswith(b"%PDF")
    pdf_text = PdfReader(BytesIO(content)).pages[0].extract_text()
    assert "Comprobante de pago" in pdf_text
    assert "49.00 USD" in pdf_text
    assert "Plan Profesional" in pdf_text
    assert paid_invoice_message(invoice, "billing@example.test")["attachments"][0]["content"] == message["attachments"][0]["content"]
    with pytest.raises(InvoiceEmailError):
        paid_invoice_message({**invoice, "status": "open"}, "billing@example.test")
    with pytest.raises(InvoiceEmailError):
        paid_invoice_message({**invoice, "invoice_pdf": "https://evil.example/invoice.pdf"}, "billing@example.test")
    with pytest.raises(InvoiceEmailError):
        paid_invoice_message({**invoice, "amount_paid": None}, "billing@example.test")


def test_receipt_has_only_central_recipient(monkeypatch):
    monkeypatch.setattr(invoice_email.settings, "smtp_only_email", "central@example.test")
    invoice = {"id": "in_123", "status": "paid", "amount_paid": 4900,
               "currency": "usd", "created": 1790000000}
    message = paid_invoice_message(invoice, "billing@example.test")
    assert message["to"] == ["central@example.test"]
    assert "bcc" not in message
    assert "billing@example.test" not in message["text"]


@pytest.mark.asyncio
async def test_resend_uses_invoice_id_as_idempotency_key(monkeypatch):
    monkeypatch.setattr(invoice_email.settings, "smtp_host", "smtp.resend.com")
    monkeypatch.setattr(invoice_email.settings, "smtp_password", "test-key")
    monkeypatch.setattr(invoice_email.settings, "smtp_from_email", "billing@example.test")
    monkeypatch.setattr(invoice_email.settings, "smtp_only_email", "central@example.test")
    captured = []
    original_client = httpx.AsyncClient

    def handler(request):
        captured.append(request)
        return httpx.Response(200, json={"id": "email-123"})

    monkeypatch.setattr(invoice_email.httpx, "AsyncClient", lambda **kw: original_client(
        transport=httpx.MockTransport(handler), **kw,
    ))
    await invoice_email.send_paid_invoice(
        {"id": "in_123", "status": "paid", "invoice_pdf": "https://pay.stripe.com/invoice/pdf/123",
         "amount_paid": 4900, "currency": "usd", "created": 1790000000},
        "billing@example.test",
    )
    assert captured[0].headers["Idempotency-Key"] == "stripe-invoice-in_123"
    assert captured[0].url == "https://api.resend.com/emails"


@pytest.mark.asyncio
async def test_paid_invoice_retries_email_without_reprocessing_completed_event(monkeypatch):
    event = {"id": "evt_paid", "type": "invoice.paid", "data": {"object": {
        "id": "in_123", "status": "paid", "customer": "cus_123",
        "customer_email": "billing@example.test",
        "invoice_pdf": "https://pay.stripe.com/invoice/pdf/123",
    }}}
    log = SimpleNamespace(estado_procesamiento="PROCESANDO", error=None, fecha_procesamiento=None)
    item = SimpleNamespace(id="sub_123", empresa_id="company-a", plan_id="plan-a",
                           estado="PENDIENTE", fecha_ultimo_pago=None)

    @asynccontextmanager
    async def nested():
        yield

    session = SimpleNamespace(
        begin_nested=nested, commit=AsyncMock(), get=AsyncMock(return_value=SimpleNamespace(email=None)),
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: item)),
    )
    request = SimpleNamespace(body=AsyncMock(return_value=b"payload"))
    sent = AsyncMock(side_effect=[InvoiceEmailError("Temporal"), None])

    async def claim(_session, _event):
        if log.estado_procesamiento == "PROCESADO":
            return None
        log.estado_procesamiento = "PROCESANDO"
        return log

    monkeypatch.setattr(subscriptions_router, "_stripe_ready", lambda **_kwargs: None)
    monkeypatch.setattr(subscriptions_router.stripe, "Webhook",
                        SimpleNamespace(construct_event=lambda *_args: event))
    monkeypatch.setattr(subscriptions_router, "_claim_stripe_event", claim)
    monkeypatch.setattr(subscriptions_router, "_sync_modules", AsyncMock())
    monkeypatch.setattr(subscriptions_router, "_audit", AsyncMock())
    monkeypatch.setattr(subscriptions_router, "send_paid_invoice", sent)

    with pytest.raises(HTTPException) as error:
        await subscriptions_router.stripe_webhook(request, "signature", session)
    assert error.value.status_code == 503
    assert log.estado_procesamiento == "FALLIDO"
    assert item.estado == "ACTIVA"
    assert item.fecha_ultimo_pago is not None

    result = await subscriptions_router.stripe_webhook(request, "signature", session)
    assert result == {"received": True}
    assert log.estado_procesamiento == "PROCESADO"
    assert log.fecha_procesamiento <= datetime.now(UTC)
    assert sent.await_count == 2
    assert await subscriptions_router.stripe_webhook(request, "signature", session) == {
        "received": True, "duplicate": True,
    }
    assert sent.await_count == 2
