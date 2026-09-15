from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ssas.bitacora.domain.catalogs import audit_level
from ssas.bitacora.domain.entities.audit_log import AuditLog

SENSITIVE_KEYS = {
    "password", "password_hash", "hashed_password", "token", "access_token",
    "refresh_token", "authorization", "secret", "app_secret_key", "smtp_password",
}


def sanitize_audit_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[OMITIDO]" if key.lower() in SENSITIVE_KEYS else sanitize_audit_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_audit_data(item) for item in value]
    return value


class RegisterAuditEvent:
    def __init__(self, repository):
        self.repository = repository

    async def execute(
        self,
        *,
        empresa_id: str | None,
        module: str,
        action: str,
        description: str,
        user_id: str | None = None,
        actor_label: str | None = None,
        affected_table: str | None = None,
        record_id: str | None = None,
        previous_data: dict[str, Any] | None = None,
        new_data: dict[str, Any] | None = None,
        source_ip: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        event = AuditLog(
            id=str(uuid4()),
            empresa_id=empresa_id,
            module=module,
            action=action,
            description=description.strip(),
            level=audit_level(action),
            created_at=datetime.now(UTC),
            user_id=user_id,
            actor_label=actor_label,
            affected_table=affected_table,
            record_id=record_id,
            previous_data=sanitize_audit_data(previous_data),
            new_data=sanitize_audit_data(new_data),
            source_ip=source_ip,
            user_agent=user_agent,
        )
        return await self.repository.add(event)
