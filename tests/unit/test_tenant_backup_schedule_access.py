import pytest
from fastapi import HTTPException

from ssas.core.security.dependencies import CurrentUser, require_empresa_permission
from ssas.respaldos.infrastructure.http.tenant_router import (
    BackupConfigRequest,
    update_tenant_backup_config,
)


@pytest.mark.asyncio
async def test_company_admin_cannot_change_another_company_schedule() -> None:
    dependency = require_empresa_permission("backup:configurar", "platform:backup:configurar")
    user = CurrentUser(id="admin", empresa_id="company-a")
    with pytest.raises(HTTPException) as denied:
        await dependency("company-b", user, None)
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_company_admin_cannot_disable_automatic_backups() -> None:
    user = CurrentUser(id="admin", empresa_id="company-a")
    with pytest.raises(HTTPException) as denied:
        await update_tenant_backup_config(
            "company-a", BackupConfigRequest(auto_habilitado=False), user, None
        )
    assert denied.value.status_code == 403
