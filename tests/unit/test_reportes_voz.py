import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from ssas.config.settings import Settings
from ssas.reportes.infrastructure.http.ai_provider import (
    GeminiReportInterpreter,
    InterpretedReport,
    ReportInterpretationError,
)
from ssas.reportes.infrastructure.http.router import interpretar
from ssas.reportes.infrastructure.http.schemas import InterpretarReporteRequest


@pytest.fixture(autouse=True)
def enabled_plan_feature(monkeypatch):
    monkeypatch.setattr(
        "ssas.reportes.infrastructure.http.router.require_plan_feature", AsyncMock()
    )


def interpretation(**overrides) -> InterpretedReport:
    data = {
        "fuente": "postulaciones",
        "columnas": [],
        "filtros": [
            {"campo": "fecha_postulacion", "operador": "mayor_igual", "valor": "2026-09-01 00:00:00"},
            {"campo": "fecha_postulacion", "operador": "menor_igual", "valor": "2026-09-30 23:59:59"},
        ],
        "orden": [{"campo": "fecha_postulacion", "direccion": "desc"}],
        "necesita_aclaracion": False,
        "aclaracion": "",
    }
    data.update(overrides)
    return InterpretedReport.model_validate(data)


@pytest.mark.asyncio
async def test_provider_sends_only_the_query_not_catalog_or_rows():
    sent = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
        assert request.headers["x-goog-api-key"] == "test-only"
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": interpretation().model_dump_json()}]
            }}],
        })

    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key="test-only")
    result = await GeminiReportInterpreter(config, httpx.MockTransport(handle)).interpret(
        "postulaciones de septiembre"
    )
    assert result.fuente == "postulaciones"
    assert sent[0]["generationConfig"]["responseMimeType"] == "application/json"
    assert sent[0]["generationConfig"]["responseSchema"]["required"] == [
        "fuente", "columnas", "filtros", "orden", "necesita_aclaracion", "aclaracion"
    ]
    sent_text = sent[0]["contents"][0]["parts"][0]["text"]
    assert json.loads(sent_text)["consulta"] == "postulaciones de septiembre"
    assert "fuentes" not in sent_text
    assert "registros" not in sent_text


@pytest.mark.asyncio
async def test_provider_falls_back_when_schema_is_rejected():
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})
        return httpx.Response(200, json={
            "candidates": [{"finishReason": "STOP", "content": {
                "parts": [{"text": interpretation().model_dump_json()}]
            }}],
        })

    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key="test-only")
    result = await GeminiReportInterpreter(config, httpx.MockTransport(handle)).interpret(
        "postulaciones de septiembre"
    )
    assert result.fuente == "postulaciones"
    assert "responseSchema" in requests[0]["generationConfig"]
    assert "responseSchema" not in requests[1]["generationConfig"]


@pytest.mark.asyncio
async def test_provider_reports_billing_error():
    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key="test-only")
    transport = httpx.MockTransport(lambda _: httpx.Response(402))
    with pytest.raises(ReportInterpretationError, match="créditos"):
        await GeminiReportInterpreter(config, transport).interpret("postulaciones")


@pytest.mark.asyncio
async def test_provider_without_key_does_not_call_external_service():
    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key=None)
    with pytest.raises(ReportInterpretationError) as error:
        await GeminiReportInterpreter(config).interpret("postulaciones de septiembre")
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_provider_rejects_incomplete_response():
    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key="test-only")
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "candidates": [{"finishReason": "MAX_TOKENS", "content": {
            "parts": [{"text": interpretation().model_dump_json()}]
        }}],
    }))
    with pytest.raises(ReportInterpretationError, match="no completó"):
        await GeminiReportInterpreter(config, transport).interpret("postulaciones")


@pytest.mark.asyncio
async def test_interpretation_uses_catalog_defaults_and_keeps_tenant_scope(monkeypatch):
    monkeypatch.setattr(
        "ssas.reportes.infrastructure.http.router.GeminiReportInterpreter.interpret",
        AsyncMock(return_value=interpretation()),
    )
    user = SimpleNamespace(empresa_id="company-a", es_plataforma=False)
    result = await interpretar(InterpretarReporteRequest(texto="postulaciones de septiembre"), None, user)
    assert result.config.fuente == "postulaciones"
    assert result.config.columnas
    assert len(result.config.filtros) == 2
    with pytest.raises(HTTPException) as error:
        await interpretar(InterpretarReporteRequest(texto="postulaciones de septiembre"), "company-b", user)
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_unknown_ai_field_requests_clarification_instead_of_running_report(monkeypatch):
    monkeypatch.setattr(
        "ssas.reportes.infrastructure.http.router.GeminiReportInterpreter.interpret",
        AsyncMock(return_value=interpretation(
            filtros=[{"campo": "salario_privado", "operador": "igual", "valor": "100"}]
        )),
    )
    user = SimpleNamespace(empresa_id="company-a", es_plataforma=False)
    result = await interpretar(InterpretarReporteRequest(texto="reporte de salarios"), None, user)
    assert result.config is None
    assert result.aclaracion


@pytest.mark.asyncio
async def test_common_date_alias_is_resolved_locally(monkeypatch):
    monkeypatch.setattr(
        "ssas.reportes.infrastructure.http.router.GeminiReportInterpreter.interpret",
        AsyncMock(return_value=interpretation(
            fuente="postulacion",
            columnas=["nombre", "fecha"],
            filtros=[{"campo": "fecha", "operador": "mayor_igual", "valor": "2026-09-01"}],
            orden=[{"campo": "fecha", "direccion": "desc"}],
        )),
    )
    user = SimpleNamespace(empresa_id="company-a", es_plataforma=False)
    result = await interpretar(InterpretarReporteRequest(texto="postulaciones de septiembre"), None, user)
    assert result.config.fuente == "postulaciones"
    assert result.config.columnas == ["postulante", "fecha_postulacion"]
    assert result.config.filtros[0].campo == "fecha_postulacion"
    assert result.config.orden[0].campo == "fecha_postulacion"
