import csv
import io
import json
import tarfile
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ssas.capacitacion.router import AsignacionInput, CursoInput, LeccionInput, lesson_view, scope
from ssas.indicadores.router import weekdays
from ssas.reportes.infrastructure.http.router import _document
from ssas.reportes.infrastructure.http.schemas import ReporteConfig
from ssas.respaldos.infrastructure.services.tenant_package import _write_package
from ssas.respaldos.infrastructure.services.tenant_restore import ValidatedPackage, file_targets


def test_course_and_assignment_validation():
    with pytest.raises(ValidationError):
        CursoInput(titulo="", nota_minima=120)
    with pytest.raises(ValidationError):
        AsignacionInput(curso_id="00000000-0000-0000-0000-000000000001")
    with pytest.raises(ValidationError):
        LeccionInput(titulo="Quiz", tipo="QUIZ", orden=1, contenido_texto='{"preguntas":[]}')


def test_quiz_answer_is_hidden_from_students():
    body = '{"preguntas":[{"enunciado":"1+1","opciones":["1","2"],"correcta":1}]}'
    LeccionInput(titulo="Quiz", tipo="QUIZ", orden=1, contenido_texto=body)
    item = SimpleNamespace(tipo="QUIZ", contenido_texto=body, __table__=SimpleNamespace(columns=[SimpleNamespace(name="contenido_texto")]))
    public = lesson_view(item)
    assert "correcta" not in json.dumps(public)
    assert json.loads(body)["preguntas"][0]["correcta"] == 1


def test_tenant_scope_rejects_other_company():
    user = SimpleNamespace(es_plataforma=False, empresa_id="a")
    assert scope(user, None) == "a"
    with pytest.raises(HTTPException) as error:
        scope(user, "b")
    assert error.value.status_code == 403


def test_csv_export_quotes_and_blocks_spreadsheet_formula():
    config = ReporteConfig(fuente="usuarios", columnas=["nombres", "email"])
    content, media = _document(config, [{"nombres": '=cmd("x")', "email": "a,b@example.com"}], "csv")
    assert content.startswith(b"\xef\xbb\xbf")
    assert media.startswith("text/csv")
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    assert rows[0] == ["nombres", "email"]
    assert rows[1] == ['\'=cmd("x")', "a,b@example.com"]


def test_workdays_include_only_weekdays():
    assert weekdays(date(2026, 11, 2), date(2026, 11, 8)) == 5


def test_tenant_backup_contains_referenced_training_material(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPACITACION_FILES_DIRECTORY", str(tmp_path / "materials"))
    monkeypatch.setattr("ssas.respaldos.infrastructure.services.tenant_package.settings.cv_storage_directory", str(tmp_path / "cv"))
    file = tmp_path / "materials" / "company-a" / "manual.pdf"
    file.parent.mkdir(parents=True)
    file.write_bytes(b"%PDF-1.4 example")
    rows = {
        "postulante": [], "postulacion": [], "documento_empleado": [],
        "leccion": [{"contenido_url": "/api/v1/capacitacion/materiales/manual.pdf"}],
    }
    archive = tmp_path / "backup.tar.gz"
    _write_package(archive, "company-a", rows, "revision")
    with tarfile.open(archive) as package:
        assert package.extractfile("files/capacitacion/manual.pdf").read() == file.read_bytes()
    package = ValidatedPackage(
        manifest={"files": [{"path": "files/capacitacion/manual.pdf", "material_name": "manual.pdf"}]},
        rows={"postulante": [], "documento_empleado": [], "leccion": rows["leccion"]},
        files={"files/capacitacion/manual.pdf": file.read_bytes()},
    )
    assert file_targets(package, "company-a")[file] == file.read_bytes()
