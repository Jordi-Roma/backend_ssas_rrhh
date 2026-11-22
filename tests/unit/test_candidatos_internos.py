from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from ssas.vacantes.infrastructure.http.router import candidatos_internos


@pytest.mark.asyncio
async def test_ranks_only_active_employees_in_requested_company() -> None:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=SimpleNamespace(id="vacancy", empresa_id="company"))
    requirements = [
        (SimpleNamespace(habilidad_id="python", peso=3, es_obligatorio=True), "Python"),
        (SimpleNamespace(habilidad_id="sql", peso=1, es_obligatorio=False), "SQL"),
    ]
    result_requirements = MagicMock()
    result_requirements.all.return_value = requirements
    employees = [
        SimpleNamespace(id="a", nombres="Ana", apellido_paterno="Paz", codigo="A1"),
        SimpleNamespace(id="b", nombres="Beto", apellido_paterno="Rios", codigo="B1"),
    ]
    skills = [
        SimpleNamespace(empleado_id="a", habilidad_id="python"),
        SimpleNamespace(empleado_id="b", habilidad_id="sql"),
    ]
    session.execute = AsyncMock(return_value=result_requirements)
    session.scalars = AsyncMock(side_effect=[MagicMock(all=MagicMock(return_value=employees)), MagicMock(all=MagicMock(return_value=skills))])
    user = SimpleNamespace(es_plataforma=False, empresa_id="company")
    response = await candidatos_internos("vacancy", "company", user, user, session)

    assert [candidate["nombre"] for candidate in response["candidatos"]] == ["Ana Paz", "Beto Rios"]
    assert response["candidatos"][0]["afinidad"] == 75.0
    assert response["candidatos"][1]["obligatorias_pendientes"] == ["Python"]
    query = session.scalar.call_args.args[0]
    assert "vacante.empresa_id" in str(query)


@pytest.mark.asyncio
async def test_rejects_other_company_before_query() -> None:
    session = MagicMock()
    user = SimpleNamespace(es_plataforma=False, empresa_id="company")
    with pytest.raises(HTTPException) as error:
        await candidatos_internos("vacancy", "other", user, user, session)
    assert error.value.status_code == 403
    session.scalar.assert_not_called()
