"""Fictional September 2025 payroll; no production employee data."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ssas.main import app
from ssas.personal.application.payroll import (
    SEED_RULES,
    PayrollConfigurationError,
    calculate_ordinary_overtime,
    calculate_payroll,
    suggest_calendar_proration,
)

MONTH_START = date(2025, 9, 1)
MONTH_END = date(2025, 9, 30)

# Historical test fixture, not a configuration for a live company. The 2025
# Gestora bulletin gives 12.71% labor SIP including 0.5% ordinary solidarity.
RATES = {
    "AFP_LABORAL_BO": Decimal("12.21"),
    "SOLIDARIO_LABORAL_BO": Decimal("0.50"),
    "CNS_PATRONAL_BO": Decimal("10.00"),
    "VIVIENDA_PATRONAL_BO": Decimal("2.00"),
    "RIESGO_PATRONAL_BO": Decimal("1.71"),
    "SOLIDARIO_PATRONAL_BO": Decimal("3.50"),
}


def seeded_rules():
    return [
        SimpleNamespace(
            codigo=code,
            nombre=name,
            tipo=kind,
            secuencia=sequence,
            tipo_calculo=method,
            base_calculo=basis,
            parametro_codigo=parameter,
            monto_fijo=None,
            activa=True,
        )
        for code, name, kind, sequence, method, basis, parameter in SEED_RULES
    ]


@pytest.mark.parametrize(
    (
        "salary",
        "contract_start",
        "unpaid",
        "overtime",
        "tax",
        "days",
        "base",
        "gross",
        "deductions",
        "net",
        "employer",
    ),
    [
        (
            "6000.50",
            MONTH_START,
            [],
            "0.00",
            "0.00",
            30,
            "6000.50",
            "6000.50",
            "762.66",
            "5237.84",
            "1032.69",
        ),
        (
            "6000.00",
            date(2025, 9, 16),
            [],
            "0.00",
            "0.00",
            15,
            "3000.00",
            "3000.00",
            "381.30",
            "2618.70",
            "516.30",
        ),
        (
            "6000.00",
            MONTH_START,
            [(date(2025, 9, 10), date(2025, 9, 11))],
            "0.00",
            "0.00",
            28,
            "5600.00",
            "5600.00",
            "711.76",
            "4888.24",
            "963.76",
        ),
        (
            "6000.00",
            MONTH_START,
            [],
            "200.00",
            "0.00",
            30,
            "6000.00",
            "6200.00",
            "788.02",
            "5411.98",
            "1067.02",
        ),
        (
            "27000.00",
            MONTH_START,
            [],
            "0.00",
            "500.00",
            30,
            "27000.00",
            "27000.00",
            "4207.50",
            "22792.50",
            "4646.70",
        ),
    ],
)
def test_complete_fictional_payroll(
    salary, contract_start, unpaid, overtime, tax, days, base, gross, deductions, net, employer
):
    suggestion = suggest_calendar_proration(
        Decimal(salary), MONTH_START, MONTH_END, contract_start, None, unpaid
    )
    assert suggestion.paid_days == days
    assert suggestion.basic_pay == Decimal(base)
    result = calculate_payroll(
        suggestion.basic_pay,
        seeded_rules(),
        RATES,
        {"HORAS_EXTRA": Decimal(overtime), "RC_IVA": Decimal(tax)},
        period_end=MONTH_END,
    )
    assert result.gross == Decimal(gross)
    assert result.deductions == Decimal(deductions)
    assert result.net == Decimal(net)
    assert result.employer_contributions == Decimal(employer)
    assert sum(line.amount for line in result.lines if line.kind == "INGRESO") == result.gross
    assert (
        sum(line.amount for line in result.lines if line.kind == "DESCUENTO") == result.deductions
    )
    assert (
        sum(line.amount for line in result.lines if line.kind == "PATRONAL")
        == result.employer_contributions
    )
    assert result.gross - result.deductions == result.net


def test_suggestion_handles_february_and_31_day_month_without_30_day_shortcut():
    february = suggest_calendar_proration(
        Decimal(3000),
        date(2024, 2, 1),
        date(2024, 2, 29),
        date(2024, 2, 16),
        None,
        [],
    )
    assert (february.paid_days, february.calendar_days, february.basic_pay) == (
        14,
        29,
        Decimal("1448.28"),
    )
    october = suggest_calendar_proration(
        Decimal(3100),
        date(2025, 10, 1),
        date(2025, 10, 31),
        date(2025, 10, 2),
        None,
        [],
    )
    assert (october.paid_days, october.calendar_days, october.basic_pay) == (
        30,
        31,
        Decimal("3000.00"),
    )


def test_ordinary_daytime_overtime_uses_contractual_day_and_double_rate():
    assert calculate_ordinary_overtime(Decimal(6000), Decimal(8), Decimal(2)) == Decimal("100.00")
    assert calculate_ordinary_overtime(Decimal(4500), Decimal(6), Decimal("1.50")) == Decimal(
        "75.00"
    )
    with pytest.raises(PayrollConfigurationError):
        calculate_ordinary_overtime(Decimal(6000), Decimal(9), Decimal(2))


def test_overlapping_unpaid_ranges_count_each_day_once():
    suggestion = suggest_calendar_proration(
        Decimal(3000),
        MONTH_START,
        MONTH_END,
        MONTH_START,
        None,
        [(date(2025, 9, 10), date(2025, 9, 12)), (date(2025, 9, 12), date(2025, 9, 13))],
    )
    assert (suggestion.unpaid_days, suggestion.paid_days, suggestion.basic_pay) == (
        4,
        26,
        Decimal("2600.00"),
    )


def test_suggestion_rejects_invalid_or_nonoverlapping_contract():
    with pytest.raises(PayrollConfigurationError, match="contrato"):
        suggest_calendar_proration(
            Decimal(3000), MONTH_START, MONTH_END, date(2025, 10, 1), None, []
        )
    with pytest.raises(PayrollConfigurationError, match="ausencia"):
        suggest_calendar_proration(
            Decimal(3000),
            MONTH_START,
            MONTH_END,
            MONTH_START,
            None,
            [(date(2025, 9, 12), date(2025, 9, 10))],
        )


def test_suggestion_route_is_documented():
    assert (
        "/api/v1/nomina/periodos/{periodo_id}/haber-proporcional/sugerencia"
        in app.openapi()["paths"]
    )
