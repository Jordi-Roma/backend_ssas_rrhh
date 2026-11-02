"""Prueba aislada: requiere una base PostgreSQL descartable ya migrada."""

import os
import shutil

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.departamentos.infrastructure.persistence.models.departamento import DepartamentoModel
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.session import AsyncSessionLocal
from ssas.respaldos.infrastructure.persistence.models.respaldo_empresa import RespaldoEmpresaModel
from ssas.respaldos.infrastructure.services import tenant_restore
from ssas.respaldos.infrastructure.services.tenant_package import create_tenant_package
from ssas.respaldos.infrastructure.services.tenant_restore import (
    create_safety_backup,
    read_tenant_package,
    restore_company,
    schema_revision,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(
    not os.getenv("TENANT_RESTORE_TEST_DATABASE_URL"),
    reason="Requiere PostgreSQL temporal explícito",
)]


async def test_restore_keeps_other_company_and_self_reference(tmp_path, monkeypatch):
    company_a = "ab000000-0000-0000-0000-000000000001"
    company_b = "ab000000-0000-0000-0000-000000000002"
    parent = "de000000-0000-0000-0000-000000000001"
    child = "de000000-0000-0000-0000-000000000002"
    other = "de000000-0000-0000-0000-000000000003"
    actor = "ab000000-0000-0000-0000-000000000099"
    async with AsyncSessionLocal() as session, session.begin():
        session.add_all([
            EmpresaModel(id=company_a, razon_social="A", nombre_comercial="A", slug="restore-a"),
            EmpresaModel(id=company_b, razon_social="B", nombre_comercial="B", slug="restore-b"),
            UserModel(id=actor, empresa_id=None, name="Admin", apellido="Global", email="restore@test.local", username="restore", hashed_password="unused"),
        ])
        session.add_all([
            DepartamentoModel(id=parent, empresa_id=company_a, nombre="Original"),
            DepartamentoModel(id=other, empresa_id=company_b, nombre="Intacto"),
        ])
        await session.flush()
        session.add(DepartamentoModel(
            id=child, empresa_id=company_a, nombre="Hijo", departamento_padre_id=parent,
        ))
    archive = tmp_path / "empresa-a.tar.gz"
    await create_tenant_package(archive, company_a)
    package = read_tenant_package(archive, company_a, await schema_revision())

    async with AsyncSessionLocal() as session, session.begin():
        first = await session.get(DepartamentoModel, parent)
        first.nombre = "Modificado"
        session.add(DepartamentoModel(
            id="de000000-0000-0000-0000-000000000004", empresa_id=company_a, nombre="Nuevo",
        ))

    class LocalR2:
        def upload(self, path, key):
            destination = tmp_path / key
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)

    monkeypatch.setattr(tenant_restore, "R2BackupStorage", LocalR2)
    safety_id = await create_safety_backup(company_a, actor)
    async with AsyncSessionLocal() as session:
        safety = await session.get(RespaldoEmpresaModel, safety_id)
    assert safety.estado == "COMPLETADO"
    safety_package = read_tenant_package(tmp_path / safety.ruta_storage, company_a, await schema_revision())
    assert {row["nombre"] for row in safety_package.rows["departamento"]} == {"Modificado", "Hijo", "Nuevo"}

    await restore_company(package, company_a, actor)

    async with AsyncSessionLocal() as session:
        a = (await session.scalars(select(DepartamentoModel).where(
            DepartamentoModel.empresa_id == company_a,
        ))).all()
        b = await session.get(DepartamentoModel, other)
    assert {item.nombre for item in a} == {"Original", "Hijo"}
    assert next(item for item in a if item.id == child).departamento_padre_id == parent
    assert b.nombre == "Intacto"

    package.rows["departamento"][1]["nombre"] = package.rows["departamento"][0]["nombre"]
    with pytest.raises(IntegrityError):
        await restore_company(package, company_a, actor)
    async with AsyncSessionLocal() as session:
        still_a = (await session.scalars(select(DepartamentoModel).where(
            DepartamentoModel.empresa_id == company_a,
        ))).all()
        still_b = await session.get(DepartamentoModel, other)
    assert {item.nombre for item in still_a} == {"Original", "Hijo"}
    assert still_b.nombre == "Intacto"
