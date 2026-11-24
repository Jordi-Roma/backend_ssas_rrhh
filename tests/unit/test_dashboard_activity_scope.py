from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from ssas.dashboard.infrastructure.http.router import _bitacora_reciente, _tendencias_mensuales


@pytest.mark.asyncio
async def test_global_dashboard_includes_company_activity_without_exposing_other_companies_to_tenant():
    session = AsyncMock()
    session.execute.return_value = MagicMock()
    session.execute.return_value.all.return_value = []

    await _bitacora_reciente(session, None)
    global_query = session.execute.call_args.args[0]
    assert " WHERE " not in str(global_query)

    await _bitacora_reciente(session, "empresa-1")
    tenant_query = session.execute.call_args.args[0]
    assert "bitacora.empresa_id =" in str(tenant_query)


@pytest.mark.asyncio
async def test_monthly_trends_include_zero_months_and_stay_within_company():
    session = AsyncMock()
    empty_result = MagicMock()
    empty_result.all.return_value = []
    session.execute.return_value = empty_result

    rows = await _tendencias_mensuales(session, "empresa-1")

    assert len(rows) == 6
    assert all(row.vacantes == 0 and row.postulaciones == 0 for row in rows)
    assert all("vacante.empresa_id =" in str(call.args[0]) for call in session.execute.call_args_list)


@pytest.mark.asyncio
async def test_monthly_trends_match_real_vacancy_and_application_counts():
    month = datetime.now(ZoneInfo("America/La_Paz")).replace(day=1)
    vacancy_result = MagicMock()
    vacancy_result.all.return_value = [(month, 3)]
    application_result = MagicMock()
    application_result.all.return_value = [(month, 7)]
    session = AsyncMock()
    session.execute.side_effect = [vacancy_result, application_result]

    rows = await _tendencias_mensuales(session, None)

    assert rows[-1].vacantes == 3
    assert rows[-1].postulaciones == 7
