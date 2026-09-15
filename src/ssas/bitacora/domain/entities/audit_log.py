from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class AuditLog:
    id: str
    empresa_id: str | None
    module: str
    action: str
    description: str
    level: str
    created_at: datetime
    user_id: str | None = None
    actor_label: str | None = None
    affected_table: str | None = None
    record_id: str | None = None
    previous_data: dict[str, Any] | None = None
    new_data: dict[str, Any] | None = None
    source_ip: str | None = None
    user_agent: str | None = None
    integrity_verified: bool | None = None
