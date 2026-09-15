from abc import ABC, abstractmethod

from ssas.bitacora.application.dto.audit_log_filter import AuditLogFilter
from ssas.bitacora.domain.entities.audit_log import AuditLog


class AuditLogRepository(ABC):
    @abstractmethod
    async def add(self, audit_log: AuditLog) -> AuditLog:
        raise NotImplementedError

    @abstractmethod
    async def list(self, filters: AuditLogFilter) -> tuple[list[AuditLog], int]:
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, audit_log_id: str, empresa_id: str | None) -> AuditLog | None:
        raise NotImplementedError

    @abstractmethod
    async def encrypted_export(self, filters: AuditLogFilter) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def verify_chain(self, empresa_id: str | None) -> tuple[bool, str | None, int]:
        raise NotImplementedError
