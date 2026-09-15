import pytest
from fastapi import HTTPException

from ssas.reportes.infrastructure.http.router import _document, _validate
from ssas.reportes.infrastructure.http.schemas import ReporteConfig


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
