from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuditLogFilter:
    empresa_id: str | None
    user_id: str | None = None
    module: str | None = None
    action: str | None = None
    level: str | None = None
    affected_table: str | None = None
    record_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    page: int = 1
    per_page: int = 50

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page
