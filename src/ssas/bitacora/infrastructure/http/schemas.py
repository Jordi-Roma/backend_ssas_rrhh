from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AuditLogSummarySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    # NULL cuando el evento es de la plataforma y no de una empresa concreta.
    empresa_id: str | None = None
    module: str
    action: str
    description: str
    level: str
    user_id: str | None = None
    actor_label: str | None = None
    affected_table: str | None = None
    record_id: str | None = None
    source_ip: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @field_validator("source_ip", mode="before")
    @classmethod
    def _ip_a_texto(cls, value):
        """La columna es INET: psycopg entrega IPv4Address, no str."""
        return None if value is None else str(value)


class AuditLogSchema(AuditLogSummarySchema):
    previous_data: dict[str, Any] | None = None
    new_data: dict[str, Any] | None = None


class AuditLogPageSchema(BaseModel):
    items: list[AuditLogSummarySchema] = Field(default_factory=list)
    total: int
    page: int
    per_page: int
    total_pages: int
