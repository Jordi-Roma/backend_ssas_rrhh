from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ssas.infrastructure.database.base import import_all_models
from ssas.usuarios.infrastructure.http.schemas import VinculoEmpleadoRequest
from ssas.usuarios.infrastructure.services.empleado_vinculo import vincular_empleado

import_all_models()

FICHA_ID = "11111111-1111-4111-8111-111111111111"
FICHA_AJENA_ID = "22222222-2222-4222-8222-222222222222"


class SessionStub:
    def __init__(self, results):
        self.results = iter(results)
        self.added = []
        self.flushed = False

    async def scalar(self, _query):
        return next(self.results)

    def add(self, instance):
        self.added.append(instance)

    async def flush(self):
        self.flushed = True


def test_requiere_una_sola_opcion():
    with pytest.raises(ValidationError):
        VinculoEmpleadoRequest()
    with pytest.raises(ValidationError):
        VinculoEmpleadoRequest(empleado_id="e", nueva_ficha={
            "codigo": "C1", "nombres": "Ana", "apellido_paterno": "Paz",
            "ci": "123", "ci_expedido": "LP", "fecha_ingreso": date(2026, 1, 1),
        })


@pytest.mark.asyncio
async def test_vincula_ficha_existente_de_la_misma_empresa():
    employee = SimpleNamespace(id=FICHA_ID, usuario_id=None)
    session = SessionStub([SimpleNamespace(id="user-1"), "rol-1", None, employee])
    result = await vincular_empleado(session, "empresa-1", "user-1", ["rol-1"],
                                     VinculoEmpleadoRequest(empleado_id=FICHA_ID))
    assert result is employee
    assert employee.usuario_id == "user-1"
    assert session.flushed


@pytest.mark.asyncio
async def test_rechaza_ficha_vinculada_a_otra_cuenta():
    employee = SimpleNamespace(id=FICHA_ID, usuario_id="otra-cuenta")
    session = SessionStub([SimpleNamespace(id="user-1"), "rol-1", None, employee])
    with pytest.raises(HTTPException) as error:
        await vincular_empleado(session, "empresa-1", "user-1", ["rol-1"],
                                VinculoEmpleadoRequest(empleado_id=FICHA_ID))
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_no_vincula_ficha_de_otra_empresa():
    session = SessionStub([SimpleNamespace(id="user-1"), "rol-1", None, None])
    with pytest.raises(HTTPException) as error:
        await vincular_empleado(session, "empresa-1", "user-1", ["rol-1"],
                                VinculoEmpleadoRequest(empleado_id=FICHA_AJENA_ID))
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_exige_rol_empleado():
    session = SessionStub([SimpleNamespace(id="user-1"), None])
    with pytest.raises(HTTPException) as error:
        await vincular_empleado(session, "empresa-1", "user-1", ["otro-rol"],
                                VinculoEmpleadoRequest(empleado_id=FICHA_ID))
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_crea_ficha_para_alta_directa():
    session = SessionStub([SimpleNamespace(id="user-1"), "rol-1", None, None])
    request = VinculoEmpleadoRequest(nueva_ficha={
        "codigo": "E001", "nombres": "Ana", "apellido_paterno": "Paz",
        "ci": "12345", "ci_expedido": "LP", "fecha_ingreso": date(2026, 1, 1),
    })
    result = await vincular_empleado(session, "empresa-1", "user-1", ["rol-1"], request)
    assert result is session.added[0]
    assert result.usuario_id == "user-1"
    assert result.empresa_id == "empresa-1"
    assert session.flushed
