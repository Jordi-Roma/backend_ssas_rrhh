from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ssas.main import app
from ssas.personal.application.attendance import minutes_late, worked_hours
from ssas.personal.application.payroll import PayrollConfigurationError, calculate_payroll
from ssas.personal.application.rc_iva import calculate_rc_iva
from ssas.personal.infrastructure.http.payroll_router import ProportionalPayInput, TaxDataInput
from ssas.personal.infrastructure.persistence.models import HaberProporcionalModel
from ssas.respaldos.infrastructure.services.tenant_package import DIRECT_TABLES


def rule(code, kind, calculation, sequence, *, parameter=None, basis=None, amount=None):
    return SimpleNamespace(
        codigo=code,
        nombre=code,
        tipo=kind,
        tipo_calculo=calculation,
        secuencia=sequence,
        parametro_codigo=parameter,
        base_calculo=basis,
        monto_fijo=amount,
        activa=True,
    )


def test_payroll_uses_ordered_rules_and_decimal_rounding():
    rules = [
        rule("DESCUENTO", "DESCUENTO", "PORCENTAJE", 2, parameter="APORTE", basis="TOTAL_GANADO"),
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule(
            "PATRONAL", "PATRONAL", "PORCENTAJE", 3, parameter="EMPLEADOR", basis="SALARIO_BASICO"
        ),
    ]
    result = calculate_payroll(
        Decimal("1000.00"),
        rules,
        {"APORTE": Decimal("10.125"), "EMPLEADOR": Decimal(3)},
    )
    assert result.gross == Decimal("1000.00")
    assert result.deductions == Decimal("101.25")
    assert result.net == Decimal("898.75")
    assert result.employer_contributions == Decimal("30.00")


def test_payroll_rejects_missing_legal_rate():
    rules = [
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule("AFP", "DESCUENTO", "PORCENTAJE", 2, parameter="AFP", basis="TOTAL_GANADO"),
    ]
    with pytest.raises(PayrollConfigurationError, match="Falta parametro"):
        calculate_payroll(Decimal(1000), rules, {})


def test_payroll_requires_verified_external_tax_amount():
    rules = [
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule("RC_IVA", "DESCUENTO", "EXTERNO", 2),
    ]
    with pytest.raises(PayrollConfigurationError, match="Falta importe verificado"):
        calculate_payroll(Decimal(1000), rules, {}, {})
    result = calculate_payroll(Decimal(1000), rules, {}, {"RC_IVA": Decimal("27.35")})
    assert result.net == Decimal("972.65")


def test_rc_iva_reproduces_sin_worksheet_example():
    result = calculate_rc_iva(
        period_end=date(2025, 6, 30),
        total_earned=Decimal(18000),
        labor_contributions=Decimal(0),
        minimum_wage=Decimal(2750),
        f110_credit=Decimal(100),
        prior_credit=Decimal(700),
        prior_credit_maintenance=Decimal(1),
    )
    assert result.taxable_income == Decimal("12500.00")
    assert result.tax_before_credits == Decimal("1625.00")
    assert result.withheld == Decimal("466.50")
    assert result.next_credit == Decimal("0.00")


def test_rc_iva_deducts_labor_contributions_and_carries_unused_credit():
    result = calculate_rc_iva(
        period_end=date(2026, 9, 30),
        total_earned=Decimal(5000),
        labor_contributions=Decimal("610.50"),
        minimum_wage=Decimal(3300),
        f110_credit=Decimal(25),
        prior_credit=Decimal(10),
        prior_credit_maintenance=Decimal(0),
    )
    assert result.withheld == Decimal("0.00")
    assert result.next_credit == Decimal("35.00")


def test_rc_iva_rejects_unsupported_period_and_invalid_inputs():
    values = {
        "total_earned": Decimal(1000),
        "labor_contributions": Decimal(0),
        "minimum_wage": Decimal(2750),
        "f110_credit": Decimal(0),
        "prior_credit": Decimal(0),
        "prior_credit_maintenance": Decimal(0),
    }
    with pytest.raises(PayrollConfigurationError, match="mayo de 2025"):
        calculate_rc_iva(period_end=date(2025, 4, 30), **values)
    with pytest.raises(PayrollConfigurationError, match="invalidos"):
        calculate_rc_iva(period_end=date(2025, 6, 30), **{**values, "f110_credit": Decimal(-1)})


def test_rc_iva_data_endpoint_requires_scoped_auth_and_validates_credits():
    from uuid import uuid4

    from pydantic import ValidationError

    payload = TaxDataInput(empleado_id=uuid4(), referencia_planilla="F110 junio 2025")
    assert payload.f110_credito == Decimal(0)
    with pytest.raises(ValidationError):
        TaxDataInput(
            empleado_id=uuid4(), referencia_planilla="F110 junio 2025", f110_credito="-1"
        )
    operation = app.openapi()["paths"]["/api/v1/nomina/periodos/{periodo_id}/rc-iva/datos"]["put"]
    assert operation["security"]
    assert app.openapi()["paths"]["/api/v1/nomina/salario-minimo"]["post"]["security"]


def test_proportional_pay_requires_reviewed_amount_and_backup_classification():
    from uuid import uuid4

    from pydantic import ValidationError

    worker = uuid4()
    data = {
        "empleado_id": worker,
        "dias_pagados": 15,
        "haber_basico_pagado": "1500.00",
        "referencia_calculo": "Planilla RRHH octubre",
    }
    assert ProportionalPayInput(**data).haber_basico_pagado == Decimal("1500.00")
    with pytest.raises(ValidationError):
        ProportionalPayInput(**{**data, "dias_pagados": 32})
    with pytest.raises(ValidationError):
        ProportionalPayInput(**{**data, "haber_basico_pagado": "0.00"})
    assert HaberProporcionalModel.__tablename__ in DIRECT_TABLES
    assert "/api/v1/nomina/periodos/{periodo_id}/haber-proporcional" in app.openapi()["paths"]


def test_ovt_monthly_payroll_field_examples_are_accepted():
    # OVT-T02 uses 30 as an example of paid days and 6000.50 as an example
    # of basic pay; they are independent field examples, not a full payslip.
    from uuid import uuid4

    entry = ProportionalPayInput(
        empleado_id=uuid4(),
        dias_pagados=30,
        haber_basico_pagado="6000.50",
        referencia_calculo="Ejemplo de campos OVT-T02",
    )
    result = calculate_payroll(
        entry.haber_basico_pagado,
        [rule("SALARIO_BASICO", "INGRESO", "BASE", 1)],
        {},
    )
    assert result.gross == Decimal("6000.50")
    assert result.net == Decimal("6000.50")


def test_payroll_blocks_income_needing_national_solidarity_contribution():
    rules = [rule("SALARIO_BASICO", "INGRESO", "BASE", 1)]
    assert calculate_payroll(Decimal("12999.99"), rules, {}).gross == Decimal("12999.99")
    with pytest.raises(PayrollConfigurationError, match="Aporte Nacional Solidario"):
        calculate_payroll(Decimal("13000.01"), rules, {})


@pytest.mark.parametrize(
    ("salary", "expected"),
    [
        ("12999.99", "0.00"),
        ("13000.00", "0.00"),
        ("13000.01", "0.00"),
        ("25000.00", "138.00"),
        ("27000.00", "275.80"),
        ("35000.00", "827.00"),
        ("36000.00", "1010.70"),
    ],
)
def test_national_solidarity_uses_cumulative_statutory_brackets(salary, expected):
    rules = [
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule("ANS", "DESCUENTO", "TRAMOS_ANS_BO", 2),
    ]
    result = calculate_payroll(Decimal(salary), rules, {}, period_end=date(2026, 9, 30))
    assert result.lines[-1].code == "ANS"
    assert result.lines[-1].amount == Decimal(expected)
    assert result.net == Decimal(salary) - Decimal(expected)


def test_national_solidarity_uses_total_income_even_if_income_rule_comes_later():
    rules = [
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule("ANS", "DESCUENTO", "TRAMOS_ANS_BO", 2),
        rule("BONO", "INGRESO", "FIJO", 3, amount="2000.00"),
    ]
    result = calculate_payroll(Decimal("25000.00"), rules, {}, period_end=date(2026, 9, 30))
    assert result.lines[-1].amount == Decimal("275.80")


def test_national_solidarity_rejects_period_before_verified_rates():
    rules = [
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule("ANS", "DESCUENTO", "TRAMOS_ANS_BO", 2),
    ]
    with pytest.raises(PayrollConfigurationError, match="vigencia"):
        calculate_payroll(Decimal("27000.00"), rules, {}, period_end=date(2024, 9, 30))


def test_only_authorized_overtime_amount_enters_gross_and_contribution_basis():
    rules = [
        rule("SALARIO_BASICO", "INGRESO", "BASE", 1),
        rule("HORAS_EXTRA", "INGRESO", "EXTERNO", 2),
        rule("AFP", "DESCUENTO", "PORCENTAJE", 3, parameter="AFP", basis="TOTAL_GANADO"),
        rule("ANS", "DESCUENTO", "TRAMOS_ANS_BO", 4),
    ]
    with pytest.raises(PayrollConfigurationError, match="Falta importe verificado"):
        calculate_payroll(Decimal(10000), rules, {"AFP": Decimal(10)}, period_end=date(2026, 9, 30))
    result = calculate_payroll(
        Decimal(10000),
        rules,
        {"AFP": Decimal(10)},
        {
            "HORAS_EXTRA": Decimal(500),
        },
        period_end=date(2026, 9, 30),
    )
    assert result.gross == Decimal("10500.00")
    assert result.deductions == Decimal("1050.00")
    assert result.net == Decimal("9450.00")


def test_personal_routes_are_documented_and_protected():
    schema = app.openapi()
    paths = schema["paths"]
    for path in (
        "/api/v1/personal/empleados/{empleado_id}/contratos",
        "/api/v1/personal/mi/asistencia/entrada",
        "/api/v1/personal/mi/ausencias",
        "/api/v1/personal/mi/asistencia/correcciones",
        "/api/v1/personal/asistencia/correcciones/{solicitud_id}/decision",
        "/api/v1/personal/mi/asistencia/horas-extra",
        "/api/v1/personal/asistencia/horas-extra/{solicitud_id}/jefe",
        "/api/v1/personal/asistencia/horas-extra/{solicitud_id}/rrhh",
        "/api/v1/nomina/periodos/{periodo_id}/calcular",
        "/api/v1/nomina/mi/boletas/{boleta_id}",
    ):
        assert path in paths
        for operation in paths[path].values():
            assert operation["security"]
            assert operation["summary"]


def test_attendance_uses_schedule_and_break():
    start = datetime(2026, 10, 24, 8, 15, tzinfo=UTC)
    end = start + timedelta(hours=9)
    assert minutes_late(start, time(8, 0)) == 15
    worked, overtime = worked_hours(start, end, 60, Decimal(8))
    assert worked == Decimal("8.00")
    assert overtime == Decimal("0.00")
