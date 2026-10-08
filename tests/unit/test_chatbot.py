from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from ssas.ayuda.infrastructure.http import chatbot_router
from ssas.ayuda.infrastructure.http.chatbot_router import _chunks, _respond
from ssas.ayuda.infrastructure.providers.gemini_chat_provider import (
    GeminiChatProvider,
    cosine,
)
from ssas.config.settings import Settings


def test_chunks_overlap_and_cosine_handles_different_dimensions():
    text = " ".join(str(number) for number in range(300))
    chunks = _chunks(text)
    assert len(chunks) == 3
    assert chunks[0].split()[-30:] == chunks[1].split()[:30]
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0], [1.0, 0.0]) == 0.0


@pytest.mark.asyncio
async def test_gemini_embedding_uses_server_key_and_validates_vector():
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "test-key"
        assert str(request.url).endswith("gemini-embedding-001:embedContent")
        return httpx.Response(200, json={"embedding": {"values": [0.5] * 768}})

    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key="test-key")
    vector = await GeminiChatProvider(config, httpx.MockTransport(handle)).embed("vacaciones")
    assert len(vector) == 768


@pytest.mark.asyncio
async def test_generated_answer_uses_only_selected_sources():
    def handle(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        assert "Politica de vacaciones" in body
        assert "Datos de otra empresa" not in body
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "Solicita el permiso en el portal."}]}}
                ]
            },
        )

    config = Settings(_env_file=None, app_secret_key="test", gemini_api_key="test-key")
    answer = await GeminiChatProvider(config, httpx.MockTransport(handle)).answer(
        "Como solicito vacaciones?", [("Politica de vacaciones", "Usa el portal de ausencias.")]
    )
    assert answer == "Solicita el permiso en el portal."


@pytest.mark.asyncio
async def test_empty_knowledge_does_not_call_gemini(monkeypatch):
    provider = AsyncMock()
    monkeypatch.setattr(chatbot_router, "GeminiChatProvider", provider)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=list)),
        scalars=AsyncMock(return_value=SimpleNamespace(all=list)),
    )
    answer = await _respond(
        "Como pido vacaciones?", "e3b83d1d-e5ee-4ff9-a4f6-dadf61a07504", True, session
    )
    assert answer["sin_respuesta"] is True
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_public_search_filters_company_and_private_articles():
    statements = []

    async def execute(statement):
        statements.append(statement)
        return SimpleNamespace(all=list)

    async def scalars(statement):
        statements.append(statement)
        return SimpleNamespace(all=list)

    company_id = "e3b83d1d-e5ee-4ff9-a4f6-dadf61a07504"
    await _respond(
        "Como pido vacaciones?", company_id, True,
        SimpleNamespace(execute=execute, scalars=scalars),
    )
    compiled = statements[0].compile()
    assert "conocimiento_articulo.publico IS true" in str(compiled)
    assert list(compiled.params.values()).count(company_id) == 2
    assert "conocimiento_articulo.publico IS true" in str(statements[1].compile())
    assert company_id in statements[1].compile().params.values()


@pytest.mark.asyncio
async def test_published_article_remains_available_when_embedding_is_missing():
    article = SimpleNamespace(
        id="article-1", titulo="Política de vacaciones", contenido="Solicita vacaciones en el portal."
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=list)),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [article])),
    )

    answer = await _respond("Como pido vacaciones?", "company-1", True, session)

    assert answer["sin_respuesta"] is False
    assert answer["fuentes"] == [{"id": "article-1", "titulo": "Política de vacaciones"}]
    compiled = session.scalars.await_args.args[0].compile()
    assert "conocimiento_articulo.publicado IS true" in str(compiled)
    assert "conocimiento_articulo.publico IS true" in str(compiled)
    assert "company-1" in compiled.params.values()


@pytest.mark.asyncio
async def test_public_source_requires_published_public_article(monkeypatch):
    company_id = "e3b83d1d-e5ee-4ff9-a4f6-dadf61a07504"
    monkeypatch.setattr(chatbot_router, "_public_company", AsyncMock(return_value=company_id))
    statements = []

    async def scalar(statement):
        statements.append(statement)

    with pytest.raises(HTTPException) as error:
        await chatbot_router.public_read_article(
            "2222", UUID("57d8a721-1d9e-4ecf-821c-1b0fba73dd28"), SimpleNamespace(scalar=scalar)
        )
    assert error.value.status_code == 404
    compiled = statements[0].compile()
    assert "conocimiento_articulo.publico IS true" in str(compiled)
    assert "conocimiento_articulo.publicado IS true" in str(compiled)
    assert company_id in compiled.params.values()
