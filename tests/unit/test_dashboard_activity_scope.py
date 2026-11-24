from unittest.mock import AsyncMock, MagicMock

import pytest

from ssas.dashboard.infrastructure.http.router import _bitacora_reciente


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
