from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ssas.core.security.dependencies import CurrentUser
from ssas.personal.infrastructure.http.router import (
    AbsenceTypeInput,
    AbsenceTypeUpdate,
    create_absence_type,
    update_absence_type,
)
from ssas.personal.infrastructure.persistence.models import TipoAusenciaModel

COMPANY = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
TYPE_ID = "00000000-0000-0000-0000-000000000003"
USER = CurrentUser(id="00000000-0000-0000-0000-000000000004", empresa_id=COMPANY)


def test_absence_type_code_and_rules_validate():
    with pytest.raises(ValidationError):
        AbsenceTypeInput(codigo="mal codigo", nombre="Prueba", es_remunerado=True)
    with pytest.raises(ValidationError):
        AbsenceTypeInput(codigo="VALIDO", nombre="Prueba", es_remunerado=True,
                         dias_maximos_anio=367)


@pytest.mark.asyncio
async def test_cannot_create_in_another_company():
    session = AsyncMock()
    payload = AbsenceTypeInput(codigo="ESTUDIO", nombre="Estudio", es_remunerado=True)
    with pytest.raises(HTTPException) as error:
        await create_absence_type(payload, UUID(OTHER), USER, session)
    assert error.value.status_code == 403
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_used_type_rules_cannot_change():
    row = TipoAusenciaModel(id=TYPE_ID, empresa_id=COMPANY, codigo="ESTUDIO",
                            nombre="Estudio", es_remunerado=True,
                            descuenta_vacacion=False, requiere_documento=False,
                            dias_maximos_anio=None, activo=True)
    session = AsyncMock()
    session.scalar.side_effect = [row, 1]
    payload = AbsenceTypeUpdate(nombre="Estudio", es_remunerado=False,
                                descuenta_vacacion=False, requiere_documento=False,
                                dias_maximos_anio=None, activo=True)
    with pytest.raises(HTTPException) as error:
        await update_absence_type(UUID(TYPE_ID), payload, None, USER, session)
    assert error.value.status_code == 409
    assert row.es_remunerado is True
    session.flush.assert_not_called()
