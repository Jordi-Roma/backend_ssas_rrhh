from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from ssas.ayuda.infrastructure.http import chatbot_router, guided_answers
from ssas.core.security.dependencies import CurrentUser

COMPANY_ID = "e3b83d1d-e5ee-4ff9-a4f6-dadf61a07504"


@pytest.mark.asyncio
async def test_public_chat_never_queries_candidates():
    session = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock())

    answer = await guided_answers.guided_answer(
        "Puedes mostrarme los postulantes?", COMPANY_ID, "empresa", None, session
    )

    assert answer["sin_respuesta"] is True
    assert "privados" in answer["respuesta"]
    session.scalar.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_candidate_summary_requires_permission_and_stays_in_tenant(monkeypatch):
    permission_codes = AsyncMock(return_value={"postulantes:ver"})
    monkeypatch.setattr(
        guided_answers,
        "SqlAlchemyAuthorizationRepository",
        lambda session: SimpleNamespace(get_user_permission_codes=permission_codes),
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=7))
    user = CurrentUser(id="user-1", empresa_id=COMPANY_ID)

    answer = await guided_answers.guided_answer(
        "Cuantos postulantes hay?", COMPANY_ID, None, user, session
    )

    assert "7 postulantes" in answer["respuesta"]
    assert answer["enlaces"] == [{"titulo": "Ver postulantes", "ruta": "/postulantes"}]
    permission_codes.assert_awaited_once_with("user-1", COMPANY_ID)
    statement = session.scalar.await_args.args[0].compile()
    assert COMPANY_ID in statement.params.values()
    assert "postulante.empresa_id" in str(statement)


@pytest.mark.asyncio
async def test_candidate_summary_denies_users_without_permission(monkeypatch):
    monkeypatch.setattr(
        guided_answers,
        "SqlAlchemyAuthorizationRepository",
        lambda session: SimpleNamespace(
            get_user_permission_codes=AsyncMock(return_value=set())
        ),
    )
    session = SimpleNamespace(scalar=AsyncMock())
    user = CurrentUser(id="user-1", empresa_id=COMPANY_ID)

    answer = await guided_answers.guided_answer(
        "Muestrame candidatos", COMPANY_ID, None, user, session
    )

    assert answer["sin_respuesta"] is True
    assert answer["enlaces"] == []
    session.scalar.assert_not_called()


@pytest.mark.asyncio
async def test_vacancies_use_public_repository_for_requested_company(monkeypatch):
    list_publicas = AsyncMock(return_value=[SimpleNamespace(id="vac-1", titulo="Enfermería")])
    monkeypatch.setattr(
        guided_answers,
        "GestionarVacantes",
        lambda repository: SimpleNamespace(listar_publicas=list_publicas),
    )
    session = SimpleNamespace()

    answer = await guided_answers.guided_answer(
        "Tienen vacantes publicadas?", COMPANY_ID, "mi-empresa", None, session
    )

    list_publicas.assert_awaited_once_with("mi-empresa", None, None)
    assert answer["enlaces"][0]["ruta"] == "/empleos/mi-empresa/vacantes/vac-1"
    assert "Enfermería" not in answer["respuesta"]


@pytest.mark.asyncio
async def test_authenticated_vacancy_lookup_requires_an_active_public_portal():
    session = SimpleNamespace(scalar=AsyncMock(return_value=None))
    user = CurrentUser(id="user-1", empresa_id=COMPANY_ID)

    answer = await guided_answers.guided_answer(
        "Hay vacantes?", COMPANY_ID, None, user, session
    )

    assert answer["sin_respuesta"] is True
    statement = session.scalar.await_args.args[0].compile()
    assert COMPANY_ID in statement.params.values()
    assert "empresa.activo IS true" in str(statement)
    assert "empresa.portal_publico_activo IS true" in str(statement)
    assert "empresa.eliminado_at IS NULL" in str(statement)


@pytest.mark.asyncio
async def test_authenticated_report_question_uses_authorized_system_guide(monkeypatch):
    visible = AsyncMock(return_value=[{
        "id": "reportes", "titulo": "Reportes", "texto": "En Reportes puedes exportar PDF.",
        "ruta": "/reportes", "permiso": "reportes:ver",
    }])
    monkeypatch.setattr(guided_answers, "_visible", visible)
    user = CurrentUser(id="user-1", empresa_id=COMPANY_ID)

    answer = await guided_answers.guided_answer(
        "Como puedo hacer reportes?", COMPANY_ID, None, user, SimpleNamespace()
    )

    assert answer["respuesta"] == "En Reportes puedes exportar PDF."
    assert answer["enlaces"] == [{"titulo": "Reportes", "ruta": "/reportes"}]
    visible.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_application_help_links_only_to_its_portal():
    answer = await guided_answers.guided_answer(
        "Como me postulo?", COMPANY_ID, "empresa", None, SimpleNamespace()
    )

    assert answer["enlaces"] == [
        {"titulo": "Ir al portal de empleo", "ruta": "/empleos/empresa"}
    ]


@pytest.mark.asyncio
async def test_guided_routes_still_reject_personal_data(monkeypatch):
    monkeypatch.setattr(chatbot_router, "_limit", lambda key: None)
    user = CurrentUser(id="user-1", empresa_id=COMPANY_ID)
    with pytest.raises(HTTPException) as error:
        await chatbot_router.message(
            chatbot_router.ChatInput(pregunta="Vacantes para persona@example.com"),
            user,
            SimpleNamespace(),
        )
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_public_message_passes_only_resolved_company_to_guided_answer(monkeypatch):
    monkeypatch.setattr(chatbot_router, "_limit", lambda key: None)
    resolve_company = AsyncMock(return_value=COMPANY_ID)
    answer = {"respuesta": "Sin datos privados", "fuentes": [], "sin_respuesta": False}
    guided = AsyncMock(return_value=answer)
    fallback = AsyncMock()
    monkeypatch.setattr(chatbot_router, "_public_company", resolve_company)
    monkeypatch.setattr(chatbot_router, "guided_answer", guided)
    monkeypatch.setattr(chatbot_router, "_respond", fallback)
    request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    session = SimpleNamespace()

    result = await chatbot_router.public_message(
        "empresa", chatbot_router.ChatInput(pregunta="Hay vacantes?"), request, session
    )

    assert result == answer
    resolve_company.assert_awaited_once_with("empresa", session)
    guided.assert_awaited_once_with("Hay vacantes?", COMPANY_ID, "empresa", None, session)
    fallback.assert_not_awaited()
