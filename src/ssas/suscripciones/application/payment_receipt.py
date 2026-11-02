"""Comprobante informativo de un pago confirmado por Stripe."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

GREEN = HexColor("#0d4938")
INK = HexColor("#172b26")
MUTED = HexColor("#65756f")
LIGHT = HexColor("#edf5ee")
LIME = HexColor("#d8f06a")


def _fit(value: object, max_width: float, size: int = 10, font: str = "Helvetica") -> str:
    text = " ".join(str(value or "-").split())
    if stringWidth(text, font, size) <= max_width:
        return text
    while text and stringWidth(text + "...", font, size) > max_width:
        text = text[:-1]
    return text.rstrip() + "..."


def _amount(invoice: dict) -> str:
    minor = invoice.get("amount_paid")
    if not isinstance(minor, int) or minor < 0:
        raise ValueError("La factura no contiene un importe pagado válido")
    currency = str(invoice.get("currency") or "").upper()
    if currency not in {"USD", "BOB"}:
        raise ValueError("Moneda no admitida para el comprobante")
    return f"{Decimal(minor) / 100:,.2f} {currency}"


def create_payment_receipt(invoice: dict, recipient: str) -> bytes:
    """Genera bytes idénticos al reintentar el mismo evento de Stripe."""
    amount = _amount(invoice)
    paid_at = (invoice.get("status_transitions") or {}).get("paid_at") or invoice.get("created")
    if not isinstance(paid_at, int) or paid_at < 0:
        raise ValueError("La factura no contiene una fecha válida")
    date = datetime.fromtimestamp(paid_at, timezone(timedelta(hours=-4))).strftime("%d/%m/%Y, %H:%M (Bolivia)")
    number = invoice.get("number") or invoice["id"]
    customer = invoice.get("customer_name") or invoice.get("customer_email") or recipient
    lines = ((invoice.get("lines") or {}).get("data") or [])
    concept = (lines[0].get("description") if lines and isinstance(lines[0], dict) else None) or "Suscripción SSAS RRHH"

    output = BytesIO()
    pdf = Canvas(output, pagesize=A4, invariant=1)
    pdf.setTitle("Comprobante de pago - SSAS RRHH")
    pdf.setAuthor("SSAS RRHH")
    width, height = A4
    left, right = 48, width - 48

    pdf.setFillColor(GREEN)
    pdf.rect(0, height - 146, width, 146, fill=1, stroke=0)
    pdf.setFillColor(LIME)
    pdf.roundRect(left, height - 81, 35, 35, 8, fill=1, stroke=0)
    pdf.setFillColor(GREEN)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawCentredString(left + 17.5, height - 71, "S")
    pdf.setFillColor(HexColor("#ffffff"))
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(left + 46, height - 59, "SSAS RRHH")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left + 46, height - 75, "Recursos Humanos")
    pdf.setFont("Helvetica-Bold", 23)
    pdf.drawString(left, height - 122, "Comprobante de pago")

    pdf.setFillColor(LIGHT)
    pdf.roundRect(left, height - 238, right - left, 66, 10, fill=1, stroke=0)
    pdf.setFillColor(GREEN)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(left + 18, height - 198, "PAGO CONFIRMADO")
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawRightString(right - 18, height - 218, amount)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left + 18, height - 218, "Suscripción")

    pdf.setFillColor(INK)
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(left, height - 278, "Detalle del pago")
    fields = [
        ("Fecha del pago", date),
        ("Referencia de Stripe", number),
        ("Titular", customer),
        ("Correo de facturación", recipient),
        ("Concepto", concept),
    ]
    y = height - 309
    for label, value in fields:
        pdf.setStrokeColor(HexColor("#dce4df"))
        pdf.line(left, y - 9, right, y - 9)
        pdf.setFont("Helvetica", 10)
        pdf.setFillColor(MUTED)
        pdf.drawString(left, y, label)
        pdf.setFont("Helvetica-Bold", 10)
        pdf.setFillColor(INK)
        pdf.drawRightString(right, y, _fit(value, 275, 10, "Helvetica-Bold"))
        y -= 44

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(left, 100, "Este comprobante confirma el pago registrado para tu suscripción.")
    pdf.drawString(left, 84, "Conserva la referencia para cualquier consulta sobre el cobro.")
    pdf.setStrokeColor(HexColor("#dce4df"))
    pdf.line(left, 63, right, 63)
    pdf.setFont("Helvetica", 8)
    pdf.drawString(left, 48, "Comprobante informativo. No sustituye una factura fiscal.")
    pdf.save()
    return output.getvalue()
