"""Deterministic payroll arithmetic; legal parameters are always explicit."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ANS_EFFECTIVE_FROM = date(2024, 10, 1)
ANS_BRACKETS = (
    (Decimal("13000.00"), Decimal("1.15")),
    (Decimal("25000.00"), Decimal("5.74")),
    (Decimal("35000.00"), Decimal("11.48")),
)

# Las tasas editables viven en parametro_valor; ANS usa la escala de la Ley 1582.
SEED_RULES = (
    ("SALARIO_BASICO", "Salario basico", "INGRESO", 10, "BASE", None, None),
    ("HORAS_EXTRA", "Horas extraordinarias autorizadas", "INGRESO", 15, "EXTERNO", None, None),
    ("AFP", "Aporte laboral SIP", "DESCUENTO", 20, "PORCENTAJE", "TOTAL_GANADO", "AFP_LABORAL_BO"),
    (
        "SOLIDARIO",
        "Aporte solidario laboral",
        "DESCUENTO",
        30,
        "PORCENTAJE",
        "TOTAL_GANADO",
        "SOLIDARIO_LABORAL_BO",
    ),
    ("ANS", "Aporte Nacional Solidario", "DESCUENTO", 35, "TRAMOS_ANS_BO", None, None),
    ("RC_IVA", "RC-IVA planilla tributaria", "DESCUENTO", 40, "EXTERNO", None, None),
    (
        "CNS_PATRONAL",
        "Caja Nacional de Salud",
        "PATRONAL",
        50,
        "PORCENTAJE",
        "TOTAL_GANADO",
        "CNS_PATRONAL_BO",
    ),
    (
        "VIVIENDA_PATRONAL",
        "Vivienda patronal",
        "PATRONAL",
        60,
        "PORCENTAJE",
        "TOTAL_GANADO",
        "VIVIENDA_PATRONAL_BO",
    ),
    (
        "RIESGO_PATRONAL",
        "Riesgo profesional",
        "PATRONAL",
        70,
        "PORCENTAJE",
        "TOTAL_GANADO",
        "RIESGO_PATRONAL_BO",
    ),
    (
        "SOLIDARIO_PATRONAL",
        "Solidario patronal",
        "PATRONAL",
        80,
        "PORCENTAJE",
        "TOTAL_GANADO",
        "SOLIDARIO_PATRONAL_BO",
    ),
)


class PayrollConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class PayrollLine:
    code: str
    name: str
    kind: str
    amount: Decimal


@dataclass(frozen=True)
class PayrollResult:
    lines: tuple[PayrollLine, ...]
    gross: Decimal
    deductions: Decimal
    net: Decimal
    employer_contributions: Decimal


@dataclass(frozen=True)
class ProrationSuggestion:
    paid_days: int
    calendar_days: int
    unpaid_days: int
    basic_pay: Decimal


def suggest_calendar_proration(
    monthly_salary: Decimal,
    month_start: date,
    month_end: date,
    contract_start: date,
    contract_end: date | None,
    unpaid_ranges: list[tuple[date, date]],
) -> ProrationSuggestion:
    """Preview only: calendar-day policy, never an approved payroll amount."""
    if monthly_salary <= 0 or month_start > month_end:
        raise PayrollConfigurationError("Salario o periodo invalido para la sugerencia")
    if month_start.year != month_end.year or month_start.month != month_end.month:
        raise PayrollConfigurationError("La sugerencia requiere un unico mes")
    first = max(month_start, contract_start)
    last = min(month_end, contract_end or month_end)
    if first > last:
        raise PayrollConfigurationError("El contrato no cubre este periodo")
    for start, end in unpaid_ranges:
        if start > end:
            raise PayrollConfigurationError("Rango de ausencia invalido")
    covered_days = (last - first).days + 1
    unpaid_dates = {
        first + timedelta(days=offset)
        for offset in range(covered_days)
        if any(start <= first + timedelta(days=offset) <= end for start, end in unpaid_ranges)
    }
    paid_days = covered_days - len(unpaid_dates)
    calendar_days = (month_end - month_start).days + 1
    basic_pay = (monthly_salary * Decimal(paid_days) / Decimal(calendar_days)).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    return ProrationSuggestion(paid_days, calendar_days, len(unpaid_dates), basic_pay)


def calculate_ordinary_overtime(
    monthly_salary: Decimal, daily_hours: Decimal, extra_hours: Decimal
) -> Decimal:
    """Company policy: 30-day monthly divisor and 100% extraordinary-hour surcharge."""
    if (
        any(not amount.is_finite() for amount in (monthly_salary, daily_hours, extra_hours))
        or monthly_salary <= 0
        or not 0 < daily_hours <= 8
        or extra_hours <= 0
    ):
        raise PayrollConfigurationError("Datos invalidos para hora extra diurna ordinaria")
    amount = (monthly_salary * extra_hours * Decimal(2) / (Decimal(30) * daily_hours)).quantize(
        CENT, rounding=ROUND_HALF_UP
    )
    if amount <= 0:
        raise PayrollConfigurationError("El importe de hora extra redondea a cero")
    return amount


def calculate_payroll(
    base_salary: Decimal,
    rules: list,
    parameters: dict[str, Decimal],
    external_amounts: dict[str, Decimal] | None = None,
    period_end: date | None = None,
) -> PayrollResult:
    if base_salary <= 0:
        raise PayrollConfigurationError("El salario basico debe ser positivo")
    lines: list[PayrollLine] = []
    totals = {"INGRESO": Decimal(0), "DESCUENTO": Decimal(0), "PATRONAL": Decimal(0)}
    seen: set[str] = set()
    ans_rule = None
    for rule in sorted(rules, key=lambda item: item.secuencia):
        if not rule.activa:
            continue
        if rule.codigo in seen or rule.tipo not in totals:
            raise PayrollConfigurationError("Reglas salariales duplicadas o invalidas")
        seen.add(rule.codigo)
        if rule.codigo == "ANS":
            if rule.tipo != "DESCUENTO" or rule.tipo_calculo != "TRAMOS_ANS_BO":
                raise PayrollConfigurationError(
                    "Configuracion invalida del Aporte Nacional Solidario"
                )
            ans_rule = rule
            continue
        if rule.tipo_calculo == "BASE":
            amount = base_salary
        elif rule.tipo_calculo == "FIJO" and rule.monto_fijo is not None:
            amount = Decimal(str(rule.monto_fijo))
        elif rule.tipo_calculo == "EXTERNO":
            if external_amounts is None or rule.codigo not in external_amounts:
                raise PayrollConfigurationError(f"Falta importe verificado para {rule.codigo}")
            amount = external_amounts[rule.codigo]
        elif rule.tipo_calculo == "PORCENTAJE":
            if not rule.parametro_codigo or rule.parametro_codigo not in parameters:
                raise PayrollConfigurationError(f"Falta parametro vigente para {rule.codigo}")
            rate = parameters[rule.parametro_codigo]
            if not 0 <= rate <= 100:
                raise PayrollConfigurationError(f"Porcentaje invalido para {rule.codigo}")
            if rule.base_calculo == "SALARIO_BASICO":
                basis = base_salary
            elif rule.base_calculo == "TOTAL_GANADO":
                basis = totals["INGRESO"]
            else:
                raise PayrollConfigurationError(f"Base de calculo no admitida para {rule.codigo}")
            amount = basis * rate / Decimal(100)
        else:
            raise PayrollConfigurationError(f"Tipo de calculo no admitido para {rule.codigo}")
        amount = amount.quantize(CENT, rounding=ROUND_HALF_UP)
        if amount < 0:
            raise PayrollConfigurationError("El monto de una regla no puede ser negativo")
        totals[rule.tipo] += amount
        lines.append(PayrollLine(rule.codigo, rule.nombre, rule.tipo, amount))
    if "SALARIO_BASICO" not in seen:
        raise PayrollConfigurationError("Falta la regla de salario basico")
    if totals["INGRESO"] > ANS_BRACKETS[0][0] and ans_rule is None:
        raise PayrollConfigurationError("Falta la regla de Aporte Nacional Solidario")
    if ans_rule is not None:
        if period_end is None or period_end < ANS_EFFECTIVE_FROM:
            raise PayrollConfigurationError(
                "Falta vigencia verificada para Aporte Nacional Solidario"
            )
        ans_amount = sum(
            (
                max(totals["INGRESO"] - threshold, Decimal(0)) * rate / Decimal(100)
                for threshold, rate in ANS_BRACKETS
            ),
            Decimal(0),
        ).quantize(CENT, rounding=ROUND_HALF_UP)
        totals["DESCUENTO"] += ans_amount
        lines.append(PayrollLine("ANS", ans_rule.nombre, "DESCUENTO", ans_amount))
    net = totals["INGRESO"] - totals["DESCUENTO"]
    if net < 0:
        raise PayrollConfigurationError("Los descuentos superan el total ganado")
    return PayrollResult(
        tuple(lines), totals["INGRESO"], totals["DESCUENTO"], net, totals["PATRONAL"]
    )
