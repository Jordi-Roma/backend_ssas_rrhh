from datetime import date, datetime, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import HTTPException

from ssas.core.security.dependencies import CurrentUser
from ssas.personal.infrastructure.http import attendance_adjustments_router as adjustments

REQUEST_ID = UUID("00000000-0000-0000-0000-000000000001")


def overtime_request(*, jefe_id="boss"):
    return SimpleNamespace(
        id=str(REQUEST_ID),
        empresa_id="company",
        empleado_id="worker",
        asistencia_id="attendance",
        estado="RRHH_PENDIENTE",
        jefe_id=jefe_id,
        monto_autorizado=None,
        referencia_calculo=None,
        rrhh_id=None,
        rrhh_en=None,
        observacion=None,
    )


def approved_payload():
    return adjustments.HRDecision(
        aprobar=True,
        observacion="Revisado con planilla",
        monto_autorizado=Decimal("120.50"),
        referencia_calculo="planilla-septiembre-2026",
    )


@pytest.mark.asyncio
async def test_boss_approval_creates_a_completely_missing_attendance(monkeypatch):
    request = SimpleNamespace(
        id=str(REQUEST_ID),
        empresa_id="company",
        empleado_id="worker",
        asistencia_id=None,
        fecha=date(2026, 9, 24),
        estado="PENDIENTE",
        nueva_entrada=datetime.fromisoformat("2026-09-24T08:00:00-04:00"),
        nueva_salida=datetime.fromisoformat("2026-09-24T17:00:00-04:00"),
        observacion_jefe=None,
        resuelto_por_id=None,
        resuelto_en=None,
    )
    contract = SimpleNamespace(
        minutos_descanso=60,
        horas_jornada=Decimal(8),
        hora_entrada_programada=time(8),
    )
    created = []

    def add(row):
        created.append(row)

    async def flush():
        created[-1].id = "new-attendance"

    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[request, contract, None]),
        add=MagicMock(side_effect=add),
        flush=AsyncMock(side_effect=flush),
    )
    monkeypatch.setattr(adjustments, "_current_boss", AsyncMock())
    monkeypatch.setattr(adjustments, "_editable_period", AsyncMock())
    monkeypatch.setattr(adjustments, "record_personal_event", AsyncMock())
    result = await adjustments.decide_correction(
        REQUEST_ID,
        adjustments.BossDecision(aprobar=True, observacion="Verificado"),
        CurrentUser(id="boss", empresa_id="company"),
        session,
    )
    assert result["estado"] == "APROBADA"
    assert request.asistencia_id == "new-attendance"
    assert created[0].horas_trabajadas == Decimal("8.00")
    assert created[0].origen == "MANUAL"


@pytest.mark.asyncio
async def test_hr_cannot_be_both_approvers():
    request = overtime_request(jefe_id="hr")
    session = SimpleNamespace(scalar=AsyncMock(return_value=request))
    with pytest.raises(HTTPException) as error:
        await adjustments.decide_overtime_hr(
            REQUEST_ID, approved_payload(), CurrentUser(id="hr", empresa_id="company"), session
        )
    assert error.value.status_code == 403
    assert request.estado == "RRHH_PENDIENTE"


@pytest.mark.asyncio
async def test_hr_cannot_authorize_own_overtime():
    request = overtime_request()
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[request, "worker"]))
    with pytest.raises(HTTPException) as error:
        await adjustments.decide_overtime_hr(
            REQUEST_ID, approved_payload(), CurrentUser(id="hr", empresa_id="company"), session
        )
    assert error.value.status_code == 403
    assert request.estado == "RRHH_PENDIENTE"


@pytest.mark.asyncio
async def test_second_approver_authorizes_only_verified_amount(monkeypatch):
    request = overtime_request()
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[request, "other-worker"]))
    monkeypatch.setattr(
        adjustments,
        "_attendance",
        AsyncMock(return_value=SimpleNamespace(fecha=date(2026, 9, 24))),
    )
    period_check = AsyncMock()
    monkeypatch.setattr(adjustments, "_editable_period", period_check)
    monkeypatch.setattr(adjustments, "record_personal_event", AsyncMock())
    result = await adjustments.decide_overtime_hr(
        REQUEST_ID, approved_payload(), CurrentUser(id="hr", empresa_id="company"), session
    )
    assert result["estado"] == "AUTORIZADO"
    assert request.monto_autorizado == Decimal("120.50")
    assert request.referencia_calculo == "planilla-septiembre-2026"
    period_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_hr_calculates_ordinary_daytime_overtime(monkeypatch):
    request = overtime_request()
    request.horas_solicitadas = Decimal(2)
    attendance = SimpleNamespace(
        fecha=date(2026, 9, 24),
        hora_salida=datetime.fromisoformat("2026-09-24T18:00:00-04:00"),
        horas_extra=Decimal(2),
    )
    contract = SimpleNamespace(salario_basico=Decimal(6000), horas_jornada=Decimal(8))
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[request, "other-worker"]),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [contract])),
    )
    monkeypatch.setattr(adjustments, "_attendance", AsyncMock(return_value=attendance))
    monkeypatch.setattr(adjustments, "_editable_period", AsyncMock())
    monkeypatch.setattr(adjustments, "record_personal_event", AsyncMock())
    decision = adjustments.HRDecision(
        aprobar=True,
        observacion="Turno diurno confirmado",
        calculo_automatico=True,
        dia_no_feriado_confirmado=True,
    )
    result = await adjustments.decide_overtime_hr(
        REQUEST_ID, decision, CurrentUser(id="hr", empresa_id="company"), session
    )
    assert result["monto_autorizado"] == Decimal("100.00")
    assert request.referencia_calculo == "AUTO_DIURNA_30D_100PCT"
    assert request.estado == "AUTORIZADO"


@pytest.mark.asyncio
async def test_hr_blocks_automatic_overtime_at_night(monkeypatch):
    request = overtime_request()
    request.horas_solicitadas = Decimal(2)
    attendance = SimpleNamespace(
        fecha=date(2026, 9, 24),
        hora_salida=datetime.fromisoformat("2026-09-24T21:00:00-04:00"),
        horas_extra=Decimal(2),
    )
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[request, "other-worker"]))
    monkeypatch.setattr(adjustments, "_attendance", AsyncMock(return_value=attendance))
    monkeypatch.setattr(adjustments, "_editable_period", AsyncMock())
    with pytest.raises(HTTPException, match="Horario nocturno"):
        await adjustments.decide_overtime_hr(
            REQUEST_ID,
            adjustments.HRDecision(
                aprobar=True,
                observacion="Turno informado",
                calculo_automatico=True,
                dia_no_feriado_confirmado=True,
            ),
            CurrentUser(id="hr", empresa_id="company"),
            session,
        )
    assert request.estado == "RRHH_PENDIENTE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("day", "confirmed"),
    [(date(2026, 9, 27), True), (date(2026, 9, 24), False)],
)
async def test_hr_requires_ordinary_nonholiday_day_for_automatic_overtime(
    monkeypatch, day, confirmed
):
    request = overtime_request()
    request.horas_solicitadas = Decimal(2)
    session = SimpleNamespace(scalar=AsyncMock(side_effect=[request, "other-worker"]))
    monkeypatch.setattr(
        adjustments,
        "_attendance",
        AsyncMock(return_value=SimpleNamespace(fecha=day)),
    )
    monkeypatch.setattr(adjustments, "_editable_period", AsyncMock())
    with pytest.raises(HTTPException, match="Dia no confirmado"):
        await adjustments.decide_overtime_hr(
            REQUEST_ID,
            adjustments.HRDecision(
                aprobar=True,
                observacion="Revision pendiente",
                calculo_automatico=True,
                dia_no_feriado_confirmado=confirmed,
            ),
            CurrentUser(id="hr", empresa_id="company"),
            session,
        )
    assert request.estado == "RRHH_PENDIENTE"
