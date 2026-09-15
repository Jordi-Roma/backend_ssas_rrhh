import pytest

from ssas.bitacora.application.dto.audit_log_filter import AuditLogFilter
from ssas.bitacora.application.use_cases.list_audit_logs import ListAuditLogs
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.domain.catalogs import AuditAction, AuditModule

pytestmark = pytest.mark.asyncio


class FakeAuditRepository:
    def __init__(self):
        self.logs = []

    async def add(self, audit_log):
        self.logs.append(audit_log)
        return audit_log

    async def list(self, filters):
        items = [log for log in self.logs if log.empresa_id == filters.empresa_id]
        return items[filters.offset : filters.offset + filters.per_page], len(items)

    async def get_by_id(self, audit_log_id, empresa_id):
        return next(
            (log for log in self.logs if log.id == audit_log_id and log.empresa_id == empresa_id),
            None,
        )


async def test_register_and_list_audit_events_are_tenant_scoped() -> None:
    repository = FakeAuditRepository()
    recorder = RegisterAuditEvent(repository)
    await recorder.execute(
        empresa_id="empresa-a",
        module=AuditModule.ROLES,
        action=AuditAction.CREATE,
        description="Rol creado",
        user_id="user-a",
    )
    await recorder.execute(
        empresa_id="empresa-b",
        module=AuditModule.AUTH,
        action=AuditAction.LOGIN,
        description="Inicio de sesión",
        user_id="user-b",
    )

    result = await ListAuditLogs(repository).execute(AuditLogFilter(empresa_id="empresa-a"))

    assert result["total"] == 1
    assert result["items"][0].empresa_id == "empresa-a"
    assert result["items"][0].module == AuditModule.ROLES
from ssas.bitacora.application.use_cases.register_audit_event import sanitize_audit_data


async def test_audit_data_removes_nested_secrets() -> None:
    result = sanitize_audit_data(
        {"email": "user@example.com", "password": "secret", "nested": {"access_token": "jwt"}}
    )

    assert result == {
        "email": "user@example.com",
        "password": "[OMITIDO]",
        "nested": {"access_token": "[OMITIDO]"},
    }
