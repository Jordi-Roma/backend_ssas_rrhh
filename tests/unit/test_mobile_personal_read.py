from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ssas.core.security.dependencies import CurrentUser
from ssas.personal.infrastructure.http.mobile_read_router import (
    my_team_absence_summary,
    my_team_summary,
    my_vacation_balances,
    router,
)


def _session(*, scalar=None, rows=(), scalars=()):
    session = MagicMock()
    session.scalar = AsyncMock(return_value=scalar)
    result = MagicMock()
    result.all.return_value = list(rows)
    session.execute = AsyncMock(return_value=result)
    scalar_result = MagicMock()
    scalar_result.all.return_value = list(scalars)
    session.scalars = AsyncMock(return_value=scalar_result)
    return session


def test_mobile_read_routes_are_separate_from_existing_routes():
    assert {route.path for route in router.routes} == {
        "/personal/mi/vacaciones",
        "/personal/mi/equipo/resumen",
        "/personal/mi/equipo/ausencias/resumen",
    }


@pytest.mark.asyncio
async def test_own_vacation_balance_uses_linked_employee():
    session = _session(
        scalar=SimpleNamespace(id="employee-1"),
        scalars=[SimpleNamespace(id="balance-1", empleado_id="employee-1",
            gestion=2026, dias_asignados=15, dias_usados=4)],
    )
    user = CurrentUser(id="user-1", empresa_id="company-1")
    result = await my_vacation_balances(user=user, session=session)
    assert result[0]["dias_saldo"] == 11
    assert result[0]["empleado_id"] == "employee-1"
    assert "saldo_vacacion.empresa_id =" in str(session.scalars.call_args.args[0].compile(
        compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_team_summary_includes_workers_without_attendance():
    session = _session(
        scalar=SimpleNamespace(id="boss-1"),
        rows=[(
            SimpleNamespace(id="contract-1", numero_contrato="C-1", estado="VIGENTE"),
            SimpleNamespace(id="employee-1", codigo="E-1", nombres="Ana",
                apellido_paterno="Lopez", apellido_materno=None),
            SimpleNamespace(id="role-1", nombre="Auxiliar"),
        )],
    )
    user = CurrentUser(id="boss-user", empresa_id="company-1")
    result = await my_team_summary(user=user, session=session)
    assert result[0]["empleado"]["nombres"] == "Ana"
    assert result[0]["asistencia"] is None


@pytest.mark.asyncio
async def test_approval_summary_contains_real_dates_and_balance():
    request = SimpleNamespace(id="request-1", fecha_inicio=__import__("datetime").date(2026, 11, 2),
        fecha_fin=__import__("datetime").date(2026, 11, 3), dias_solicitados=2,
        motivo="Vacaciones", documento_url=None, estado="PENDIENTE",
        observacion_jefe=None, creado_en=None, resuelto_en=None)
    worker = SimpleNamespace(id="employee-1", nombres="Ana",
        apellido_paterno="Lopez", apellido_materno=None)
    kind = SimpleNamespace(id="type-1", codigo="VAC", nombre="Vacacion",
        es_remunerado=True, descuenta_vacacion=True, requiere_documento=False)
    balance = SimpleNamespace(id="balance-1", empleado_id="employee-1",
        gestion=2026, dias_asignados=15, dias_usados=4)
    session = _session(rows=[(request, worker, kind)], scalars=[balance])
    user = CurrentUser(id="manager", empresa_id="company-1", roles=["RRHH"])
    result = await my_team_absence_summary(user=user, session=session)
    assert result[0]["saldo"]["dias_saldo"] == 11
    assert result[0]["motivo"] == "Vacaciones"
