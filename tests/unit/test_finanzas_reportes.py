from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ssas.core.security.dependencies import CurrentUser
from ssas.reportes.infrastructure.http.finanzas_router import resumen_financiero


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    async def execute(self, statement):
        assert "entorno_prueba" in str(statement)
        return FakeResult([
            SimpleNamespace(fecha=date(2026, 11, 2), tipo="INGRESO", monto=Decimal("20.00"), categoria="PRO"),
            SimpleNamespace(fecha=date(2026, 11, 5), tipo="REEMBOLSO", monto=Decimal("4.00"), categoria="STRIPE"),
            SimpleNamespace(fecha=date(2026, 11, 9), tipo="GASTO", monto=Decimal("3.50"), categoria="BACKUP"),
        ])


@pytest.mark.asyncio
async def test_financial_report_separates_paid_refunded_and_expense():
    user = CurrentUser(id="admin", empresa_id=None)
    result = await resumen_financiero(date(2026, 11, 1), date(2026, 11, 30), "USD", user, FakeSession())
    assert result["ingresos"] == Decimal("20.00")
    assert result["reembolsos"] == Decimal("4.00")
    assert result["gastos"] == Decimal("3.50")
    assert result["saldo_parcial"] == Decimal("12.50")
    assert result["cobros"] == 1
    assert result["ventas_por_plan"] == [{"plan": "PRO", "monto": Decimal("20.00")}]
