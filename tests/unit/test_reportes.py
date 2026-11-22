import re
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.postulaciones.infrastructure.persistence.models.postulacion import PostulacionModel
from ssas.postulantes.infrastructure.persistence.models.postulante import PostulanteModel
from ssas.reportes.infrastructure.http.router import (
    FROM_SQL,
    SOURCES,
    TENANT_COLUMN,
    _document,
    _rows,
    _validate,
    grafico,
)


def test_absence_report_labels_missing_historical_department() -> None:
    assert "Sin departamento en esa fecha" in SOURCES["ausencias"]["departamento"]
    assert "c.fecha_fin>=sa.fecha_inicio" in FROM_SQL["ausencias"]
    assert TENANT_COLUMN["ausencias"] == "sa.empresa_id"
from ssas.reportes.infrastructure.http.schemas import GraficoConfig, ReporteConfig
from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel


def test_report_catalog_rejects_unknown_columns() -> None:
    config = ReporteConfig(fuente="usuarios", columnas=["password_hash"])

    with pytest.raises(HTTPException) as error:
        _validate(config)

    assert error.value.status_code == 422


@pytest.mark.parametrize(
    ("format", "signature"),
    [("html", b"<!doctype html>"), ("xlsx", b"PK"), ("pdf", b"%PDF")],
)
def test_exports_create_real_documents(format: str, signature: bytes) -> None:
    config = ReporteConfig(fuente="usuarios", columnas=["nombres", "email"])

    content, media_type = _document(
        config, [{"nombres": "Ana", "email": "ana@example.com"}], format
    )

    assert content.startswith(signature)
    assert media_type


@pytest.mark.asyncio
async def test_postulaciones_report_uses_real_columns_and_tenant_scope() -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    config = ReporteConfig(
        fuente="postulaciones",
        columnas=["postulante", "puntaje"],
        filtros=[{"campo": "estado", "operador": "igual", "valor": "ACTIVA"}],
    )

    assert await _rows(session, "empresa-a", config) == []
    statement, params = session.execute.await_args.args
    sql = str(statement)
    assert "v.empresa_id = :empresa_id" in sql
    assert "p.empresa_id=v.empresa_id" in sql
    assert "COALESCE(po.puntaje_manual, po.puntaje_ia) AS puntaje" in sql
    assert "po.empresa_id" not in sql
    assert "po.puntaje_final" not in sql
    assert params == {"empresa_id": "empresa-a", "v0": "ACTIVA"}


def test_all_report_columns_exist_in_the_database_models() -> None:
    aliases = {
        "v": set(VacanteModel.__table__.columns.keys()),
        "u": set(UserModel.__table__.columns.keys()),
        "po": set(PostulacionModel.__table__.columns.keys()),
        "p": set(PostulanteModel.__table__.columns.keys()),
    }
    for source, columns in SOURCES.items():
        expressions = [*columns.values(), FROM_SQL[source], TENANT_COLUMN[source]]
        for expression in expressions:
            for alias, column in re.findall(r"\b(v|u|po|p)\.([a-z_]+)\b", expression):
                assert column in aliases[alias], f"{source}: {alias}.{column} no existe"


@pytest.mark.asyncio
async def test_chart_aggregates_all_filtered_rows_with_tenant_scope() -> None:
    session = MagicMock()
    total = MagicMock(); total.mappings.return_value.one.return_value = {"total": 85, "value": 85}
    groups = MagicMock(); groups.mappings.return_value.all.return_value = [
        {"label": "ACTIVA", "count": 65, "value": 65},
        {"label": "RETIRADA", "count": 15, "value": 15},
    ]
    session.execute = AsyncMock(side_effect=[total, groups])
    user = SimpleNamespace(empresa_id="empresa-a", es_plataforma=False)
    body = GraficoConfig(fuente="postulaciones", columnas=["postulante"], campo="estado",
                         filtros=[{"campo": "fecha_postulacion", "operador": "mayor_igual", "valor": "2026-09-01"}])
    with patch("ssas.reportes.infrastructure.http.router.require_plan_feature", new_callable=AsyncMock):
        result = await grafico(body, None, user, session)
    assert result["total"] == 85
    assert result["grupos"][-1] == {"label": "Otros", "count": 5, "value": 5}
    statement, params = session.execute.await_args_list[1].args
    assert "v.empresa_id = :empresa_id" in str(statement)
    assert "po.fecha_postulacion >= :v0" in str(statement)
    assert "GROUP BY 1" in str(statement)
    assert params == {"empresa_id": "empresa-a", "v0": "2026-09-01"}


@pytest.mark.asyncio
@pytest.mark.parametrize("source, field", [
    ("vacantes", "estado"),
    ("usuarios", "username"),
    ("postulaciones", "postulante"),
])
@pytest.mark.parametrize("operator, value, fragment", [
    ("igual", "ACTIVA", " = :v0"),
    ("contiene", "Ana", " ILIKE :v0"),
    ("mayor_igual", "A", " >= :v0"),
    ("menor_igual", "Z", " <= :v0"),
])
async def test_filters_work_for_every_report_source(
    source: str, field: str, operator: str, value: str, fragment: str
) -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    config = ReporteConfig(
        fuente=source,
        columnas=list(SOURCES[source]),
        filtros=[{"campo": field, "operador": operator, "valor": value}],
        orden=[{"campo": field, "direccion": "desc"}],
    )

    assert await _rows(session, "empresa-a", config) == []
    statement, params = session.execute.await_args.args
    sql = str(statement)
    assert f"{TENANT_COLUMN[source]} = :empresa_id" in sql
    assert fragment in sql
    assert " ORDER BY " in sql and " DESC" in sql
    assert params["empresa_id"] == "empresa-a"
    assert params["v0"] == (f"%{value}%" if operator == "contiene" else value)


@pytest.mark.asyncio
@pytest.mark.parametrize("source, date_field", [
    ("vacantes", "fecha_publicacion"),
    ("usuarios", "ultimo_acceso"),
    ("postulaciones", "fecha_postulacion"),
])
async def test_date_range_filter_works_for_every_report_source(
    source: str, date_field: str
) -> None:
    session = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    config = ReporteConfig(
        fuente=source,
        columnas=[date_field],
        filtros=[{
            "campo": date_field,
            "operador": "entre",
            "valor": ["2026-10-01", "2026-10-31"],
        }],
    )

    assert await _rows(session, "empresa-a", config) == []
    statement, params = session.execute.await_args.args
    assert " BETWEEN :v0a AND :v0b" in str(statement)
    assert params == {
        "empresa_id": "empresa-a",
        "v0a": "2026-10-01",
        "v0b": "2026-10-31",
    }
