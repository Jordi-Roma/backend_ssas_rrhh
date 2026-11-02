import tarfile

import pytest

from ssas.config.settings import settings
from ssas.infrastructure.database.base import import_all_models
from ssas.respaldos.infrastructure.services.errors import TenantBackupError
from ssas.respaldos.infrastructure.services.tenant_package import (
    CHILD_TABLES,
    DIRECT_TABLES,
    _write_package,
)
from ssas.respaldos.infrastructure.services.tenant_restore import (
    ValidatedPackage,
    file_targets,
    install_files,
    read_tenant_package,
    table_order,
    undo_files,
)


def empty_package(tmp_path):
    rows = {name: [] for name in DIRECT_TABLES}
    rows.update({name: [] for name, _, _ in CHILD_TABLES})
    path = tmp_path / "company.tar.gz"
    _write_package(path, "company-a", rows, "revision-a")
    return path


def test_restoration_accepts_own_package_with_all_tables(tmp_path):
    import_all_models()
    package = read_tenant_package(empty_package(tmp_path), "company-a", "revision-a")
    assert len(package.rows) == len(DIRECT_TABLES) + len(CHILD_TABLES)
    assert file_targets(package, "company-a") == {}
    order = table_order()
    assert order.index("usuario") < order.index("usuario_rol")
    assert order.index("postulacion") < order.index("postulacion_nota")


def test_restoration_rejects_other_company_or_schema(tmp_path):
    import_all_models()
    path = empty_package(tmp_path)
    with pytest.raises(TenantBackupError, match="incompatibles"):
        read_tenant_package(path, "company-b", "revision-a")
    with pytest.raises(TenantBackupError, match="incompatibles"):
        read_tenant_package(path, "company-a", "revision-b")


def test_restoration_rejects_extra_file(tmp_path):
    import_all_models()
    path = empty_package(tmp_path)
    altered = tmp_path / "altered.tar.gz"
    with tarfile.open(path, "r:gz") as original, tarfile.open(altered, "w:gz") as archive:
        for member in original.getmembers():
            archive.addfile(member, original.extractfile(member))
        archive.add(__file__, arcname="extra.txt")
    with pytest.raises(TenantBackupError):
        read_tenant_package(altered, "company-a", "revision-a")


def test_file_replacement_can_be_reverted_without_touching_other_company(tmp_path):
    own = tmp_path / "company-a" / "cv.pdf"
    other = tmp_path / "company-b" / "cv.pdf"
    own.parent.mkdir()
    other.parent.mkdir()
    own.write_bytes(b"newer")
    other.write_bytes(b"unrelated")
    stack, changes = install_files({own: b"original"})
    try:
        assert own.read_bytes() == b"original"
        undo_files(changes)
        assert own.read_bytes() == b"newer"
        assert other.read_bytes() == b"unrelated"
    finally:
        stack.close()


def test_file_targets_accept_only_current_company_paths(tmp_path, monkeypatch):
    cv_root = tmp_path / "cv"
    doc_root = tmp_path / "documents"
    monkeypatch.setattr(settings, "cv_storage_directory", str(cv_root))
    monkeypatch.setattr(settings, "employee_files_directory", str(doc_root))
    package = ValidatedPackage(
        manifest={"files": [
            {"path": "files/cv/one.pdf", "cv_url": "/old/cv/CODE.pdf"},
            {"path": "files/employee-documents/two.pdf", "documento_id": "doc-1"},
        ]},
        rows={
            "postulante": [{"cv_url": "/old/cv/CODE.pdf"}],
            "documento_empleado": [{"id": "doc-1", "ruta_privada": str(doc_root / "company-a" / "emp-1" / "contract.pdf")}],
        },
        files={"files/cv/one.pdf": b"cv", "files/employee-documents/two.pdf": b"contract"},
    )
    targets = file_targets(package, "company-a")
    assert targets[cv_root / "CODE.pdf"] == b"cv"
    assert targets[doc_root / "company-a" / "emp-1" / "contract.pdf"] == b"contract"
    package.rows["documento_empleado"][0]["ruta_privada"] = str(doc_root / "company-b" / "contract.pdf")
    with pytest.raises(TenantBackupError, match="fuera de la empresa"):
        file_targets(package, "company-a")
