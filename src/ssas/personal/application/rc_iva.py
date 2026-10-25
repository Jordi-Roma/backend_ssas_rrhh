"""RC-IVA dependent-worker worksheet arithmetic (SIN, May 2025 onward)."""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from ssas.personal.application.payroll import PayrollConfigurationError

CENT = Decimal("0.01")
RATE = Decimal("0.13")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class RcIvaResult:
    withheld: Decimal
    next_credit: Decimal
    next_siete_rg: Decimal
    taxable_income: Decimal
    tax_before_credits: Decimal


def calculate_rc_iva(
    *,
    period_end: date,
    total_earned: Decimal,
    labor_contributions: Decimal,
    minimum_wage: Decimal,
    f110_credit: Decimal,
    prior_credit: Decimal,
    prior_credit_maintenance: Decimal,
    prior_siete_rg: Decimal = Decimal(0),
    f110_siete_rg: Decimal = Decimal(0),
) -> RcIvaResult:
    if period_end < date(2025, 5, 1):
        raise PayrollConfigurationError("RC-IVA automatico solo admite periodos desde mayo de 2025")
    amounts = (
        total_earned,
        labor_contributions,
        minimum_wage,
        f110_credit,
        prior_credit,
        prior_credit_maintenance,
        prior_siete_rg,
        f110_siete_rg,
    )
    if any(value < 0 or not value.is_finite() for value in amounts) or minimum_wage == 0:
        raise PayrollConfigurationError("Importes RC-IVA invalidos")
    if labor_contributions > total_earned:
        raise PayrollConfigurationError("Aportes laborales superiores al total ganado")
    taxable_income = money(max(Decimal(0), total_earned - labor_contributions - 2 * minimum_wage))
    tax_before_credits = money(taxable_income * RATE)
    tax_after_smn = max(Decimal(0), tax_before_credits - money(minimum_wage * RATE))
    tax_after_f110 = max(Decimal(0), tax_after_smn - f110_credit)
    credit_generated = max(Decimal(0), f110_credit - tax_after_smn)
    available_credit = prior_credit + prior_credit_maintenance
    credit_used = min(tax_after_f110, available_credit)
    tax_after_credit = tax_after_f110 - credit_used
    available_siete_rg = prior_siete_rg + f110_siete_rg
    siete_rg_used = min(tax_after_credit, available_siete_rg)
    return RcIvaResult(
        withheld=money(tax_after_credit - siete_rg_used),
        next_credit=money(available_credit - credit_used + credit_generated),
        next_siete_rg=money(available_siete_rg - siete_rg_used),
        taxable_income=taxable_income,
        tax_before_credits=tax_before_credits,
    )
