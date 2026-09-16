from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from ssas.suscripciones.application.reconciliation import derived_status
from ssas.suscripciones.infrastructure.http.router import _map_status


def subscription(**overrides):
    values = {
        "estado": "ACTIVA",
        "periodo_prueba_hasta": None,
        "fecha_fin": None,
        "cancelar_al_fin_periodo": False,
        "updated_at": datetime.now(UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_maps_stripe_statuses() -> None:
    assert _map_status("active") == "ACTIVA"
    assert _map_status("trialing") == "PRUEBA"
    assert _map_status("past_due") == "PAGO_FALLIDO"
    assert _map_status("canceled") == "CANCELADA"


def test_expired_trial_becomes_expired() -> None:
    today = datetime.now(UTC).date()
    item = subscription(estado="PRUEBA", periodo_prueba_hasta=today - timedelta(days=1))
    assert derived_status(item, today=today, now=datetime.now(UTC), grace_days=3) == "VENCIDA"


def test_failed_payment_is_suspended_after_grace_period() -> None:
    item = subscription(
        estado="PAGO_FALLIDO",
        updated_at=datetime.now(UTC) - timedelta(days=4),
    )
    assert derived_status(item, today=datetime.now(UTC).date(), now=datetime.now(UTC), grace_days=3) == "SUSPENDIDA"


def test_future_active_subscription_is_unchanged() -> None:
    today = datetime.now(UTC).date()
    item = subscription(fecha_fin=today + timedelta(days=30))
    assert derived_status(item, today=today, now=datetime.now(UTC), grace_days=3) == "ACTIVA"
