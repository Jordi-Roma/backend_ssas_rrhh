import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ssas.suscripciones.infrastructure.http.feature_guard import require_plan_feature
from ssas.suscripciones.infrastructure.http.schemas import PlanRequest


class FakeSession:
    def __init__(self, features: list[str] | None):
        self.features = features

    async def scalar(self, _query):
        return self.features


@pytest.mark.asyncio
async def test_feature_requires_both_matching_plan_and_role_guard() -> None:
    await require_plan_feature(FakeSession(["analisis_cv_ia"]), "company-a", "analisis_cv_ia")
    with pytest.raises(HTTPException) as denied:
        await require_plan_feature(FakeSession([]), "company-a", "analisis_cv_ia")
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as missing:
        await require_plan_feature(FakeSession(None), "company-a", "horario_respaldo")
    assert missing.value.status_code == 403


def test_plan_only_accepts_existing_feature_codes() -> None:
    base = {
        "nombre": "Plan prueba", "precio_mensual": "49", "max_usuarios": 5,
        "max_vacantes_activas": 5, "max_almacenamiento_mb": 250,
    }
    assert PlanRequest(**base, funciones=["importacion_masiva"]).funciones == [
        "importacion_masiva"
    ]
    with pytest.raises(ValidationError):
        PlanRequest(**base, funciones=["funcion_inventada"])
