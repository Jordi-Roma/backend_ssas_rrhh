import hashlib
import json
import tarfile

import pytest
from fastapi import HTTPException

from ssas.config.settings import settings
from ssas.core.security.dependencies import CurrentUser
from ssas.respaldos.infrastructure.http.tenant_router import _scope
from ssas.respaldos.infrastructure.services.errors import TenantBackupError
from ssas.respaldos.infrastructure.services.tenant_jobs import _failure_detail
from ssas.respaldos.infrastructure.services.tenant_package import (
    _check_table_inventory,
    _write_package,
)


def test_backup_failure_details_only_include_approved_messages() -> None:
    assert _failure_detail(TenantBackupError("Un CV no está disponible"), "empaquetado") == (
        "empaquetado: Un CV no está disponible"
    )
    assert _failure_detail(RuntimeError("secret-value"), "subida R2") == (
        "subida R2: RuntimeError"
    )


def test_tenant_scope_never_accepts_another_company() -> None:
    user = CurrentUser(id="user-a", empresa_id="company-a")
    assert _scope(user, None) == "company-a"
    assert _scope(user, "company-a") == "company-a"
    with pytest.raises(HTTPException) as error:
        _scope(user, "company-b")
    assert error.value.status_code == 403
    assert _scope(CurrentUser(id="admin", empresa_id=None), "company-b") == "company-b"


def test_all_tables_are_classified_for_tenant_export() -> None:
    _check_table_inventory()


def test_package_contains_manifest_and_only_referenced_cv(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cv_storage_directory", str(tmp_path))
    cv = tmp_path / "A-123.pdf"
    cv.write_bytes(b"sample-cv")
    (tmp_path / "B-999.pdf").write_bytes(b"other-company-cv")
    rows = {
        "postulante": [{"id": "candidate-a", "cv_url": str(cv)}],
        "postulacion": [{"postulante_id": "candidate-a", "codigo_seguimiento": "A-123"}],
    }
    package = tmp_path / "tenant.tar.gz"

    _write_package(package, "company-a", rows, "20261006_0010")

    with tarfile.open(package, "r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        data = archive.extractfile("data.json").read()
        assert manifest["empresa_id"] == "company-a"
        assert manifest["schema_revision"] == "20261006_0010"
        assert manifest["data_sha256"] == hashlib.sha256(data).hexdigest()
        assert len(manifest["files"]) == 1
        entry = manifest["files"][0]
        assert archive.extractfile(entry["path"]).read() == b"sample-cv"
        assert entry["sha256"] == hashlib.sha256(b"sample-cv").hexdigest()
        assert len(archive.getnames()) == 3


def test_package_rejects_cv_without_own_tracking_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "cv_storage_directory", str(tmp_path))
    cv = tmp_path / "B-999.pdf"
    cv.write_bytes(b"other-company-cv")
    rows = {
        "postulante": [{"id": "candidate-a", "cv_url": str(cv)}],
        "postulacion": [{"postulante_id": "candidate-a", "codigo_seguimiento": "A-123"}],
    }
    with pytest.raises(RuntimeError, match="no corresponde"):
        _write_package(tmp_path / "tenant.tar.gz", "company-a", rows, "20261006_0010")


def test_package_includes_only_owned_employee_documents(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "employee_files_directory", str(tmp_path))
    own = tmp_path / "company-a" / "employee-a"
    own.mkdir(parents=True)
    document = own / "contract.pdf"
    document.write_bytes(b"private-contract")
    other = tmp_path / "company-b" / "employee-b"
    other.mkdir(parents=True)
    (other / "contract.pdf").write_bytes(b"other-company")
    rows = {
        "postulante": [], "postulacion": [],
        "documento_empleado": [{"id": "document-a", "ruta_privada": str(document)}],
    }
    package = tmp_path / "company-a.tar.gz"
    _write_package(package, "company-a", rows, "20261024_0011")
    with tarfile.open(package, "r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        assert len(manifest["files"]) == 1
        assert archive.extractfile(manifest["files"][0]["path"]).read() == b"private-contract"
        assert b"other-company" not in archive.extractfile("data.json").read()


def test_package_rejects_document_outside_tenant_directory(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "employee_files_directory", str(tmp_path))
    other = tmp_path / "company-b" / "employee-b"
    other.mkdir(parents=True)
    document = other / "contract.pdf"
    document.write_bytes(b"other-company")
    rows = {
        "postulante": [], "postulacion": [],
        "documento_empleado": [{"id": "document-b", "ruta_privada": str(document)}],
    }
    with pytest.raises(TenantBackupError, match="documento"):
        _write_package(tmp_path / "company-a.tar.gz", "company-a", rows, "20261024_0011")
