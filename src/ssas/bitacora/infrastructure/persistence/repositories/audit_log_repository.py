from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.dto.audit_log_filter import AuditLogFilter
from ssas.bitacora.domain.entities.audit_log import AuditLog
from ssas.bitacora.infrastructure.crypto import AuditCipher, encrypted_line, record_hash
from ssas.bitacora.infrastructure.persistence.models.audit_log import AuditLogModel
from ssas.bitacora.ports.outgoing.audit_log_repository import AuditLogRepository
from ssas.config.settings import settings


def _metadata(value: AuditLog | AuditLogModel) -> dict:
    return {
        "id": value.id,
        "empresa_id": value.empresa_id,
        "usuario_id": value.user_id,
        "modulo": value.module,
        "accion": value.action,
        "nivel": value.level,
        "tabla_afectada": value.affected_table if isinstance(value, AuditLog) else value.tabla_afectada,
        "registro_id": value.record_id if isinstance(value, AuditLog) else value.registro_id,
        "fecha": (value.created_at if isinstance(value, AuditLog) else value.fecha).isoformat(),
    }


class SqlAlchemyAuditLogRepository(AuditLogRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, audit_log: AuditLog) -> AuditLog:
        cipher = AuditCipher(settings.app_audit_encryption_key)
        scope = audit_log.empresa_id or "PLATFORM"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:scope))"),
            {"scope": f"bitacora:{scope}"},
        )
        previous_result = await self.session.execute(
            select(AuditLogModel.hash_registro)
            .where(
                AuditLogModel.empresa_id == audit_log.empresa_id
                if audit_log.empresa_id is not None
                else AuditLogModel.empresa_id.is_(None)
            )
            .order_by(AuditLogModel.fecha.desc(), AuditLogModel.id.desc())
            .limit(1)
        )
        previous_hash = previous_result.scalar_one_or_none()
        payload = {
            "actor_label": audit_log.actor_label,
            "description": audit_log.description,
            "previous_data": audit_log.previous_data,
            "new_data": audit_log.new_data,
            "source_ip": audit_log.source_ip,
            "user_agent": audit_log.user_agent,
        }
        metadata = _metadata(audit_log)
        ciphertext, nonce = cipher.encrypt(payload, metadata)
        current_hash = record_hash(previous_hash, metadata, nonce, ciphertext)
        self.session.add(
            AuditLogModel(
                id=audit_log.id,
                empresa_id=audit_log.empresa_id,
                user_id=audit_log.user_id,
                actor_label=None,
                module=audit_log.module,
                action=audit_log.action,
                level=audit_log.level,
                description="[CIFRADO]",
                tabla_afectada=audit_log.affected_table,
                registro_id=audit_log.record_id,
                datos_previos_jsonb=None,
                datos_nuevos_jsonb=None,
                ip_origen=None,
                user_agent=None,
                fecha=audit_log.created_at,
                datos_cifrados=ciphertext,
                nonce_cifrado=nonce,
                version_cifrado=cipher.version,
                hash_anterior=previous_hash,
                hash_registro=current_hash,
            )
        )
        await self.session.flush()
        return audit_log

    async def list(self, filters: AuditLogFilter) -> tuple[list[AuditLog], int]:
        conditions = self._conditions(filters)
        total_result = await self.session.execute(
            select(func.count(AuditLogModel.id)).where(*conditions)
        )
        result = await self.session.execute(
            select(AuditLogModel)
            .where(*conditions)
            .order_by(AuditLogModel.fecha.desc())
            .offset(filters.offset)
            .limit(filters.per_page)
        )
        return [self._to_summary(model) for model in result.scalars().all()], total_result.scalar_one()

    async def get_by_id(self, audit_log_id: str, empresa_id: str | None) -> AuditLog | None:
        result = await self.session.execute(
            select(AuditLogModel).where(
                AuditLogModel.id == audit_log_id,
                AuditLogModel.empresa_id == empresa_id
                if empresa_id is not None
                else AuditLogModel.empresa_id.is_(None),
            )
        )
        model = result.scalar_one_or_none()
        return self._to_detail(model) if model else None

    async def encrypted_export(self, filters: AuditLogFilter) -> bytes:
        result = await self.session.execute(
            select(AuditLogModel)
            .where(*self._conditions(filters))
            .order_by(AuditLogModel.fecha.asc(), AuditLogModel.id.asc())
        )
        return b"".join(encrypted_line(model) for model in result.scalars().all())

    async def verify_chain(self, empresa_id: str | None) -> tuple[bool, str | None, int]:
        condition = (
            AuditLogModel.empresa_id == empresa_id
            if empresa_id is not None
            else AuditLogModel.empresa_id.is_(None)
        )
        result = await self.session.execute(
            select(AuditLogModel)
            .where(condition)
            .order_by(AuditLogModel.fecha.asc(), AuditLogModel.id.asc())
        )
        previous_hash = None
        count = 0
        for model in result.scalars().all():
            count += 1
            if not model.datos_cifrados or not model.nonce_cifrado:
                return False, model.id, count
            expected = record_hash(previous_hash, _metadata(model), model.nonce_cifrado, model.datos_cifrados)
            if model.hash_anterior != previous_hash or model.hash_registro != expected:
                return False, model.id, count
            previous_hash = model.hash_registro
        return True, None, count

    @staticmethod
    def _conditions(filters: AuditLogFilter) -> list:
        conditions = [
            AuditLogModel.empresa_id == filters.empresa_id
            if filters.empresa_id is not None
            else AuditLogModel.empresa_id.is_(None)
        ]
        if filters.user_id:
            conditions.append(AuditLogModel.user_id == filters.user_id)
        if filters.module:
            conditions.append(AuditLogModel.module == filters.module)
        if filters.action:
            conditions.append(AuditLogModel.action == filters.action)
        if filters.level:
            conditions.append(AuditLogModel.level == filters.level)
        if filters.affected_table:
            conditions.append(AuditLogModel.tabla_afectada == filters.affected_table)
        if filters.record_id:
            conditions.append(AuditLogModel.registro_id == filters.record_id)
        if filters.start_date:
            conditions.append(AuditLogModel.fecha >= filters.start_date)
        if filters.end_date:
            conditions.append(AuditLogModel.fecha <= filters.end_date)
        return conditions

    @staticmethod
    def _to_summary(model: AuditLogModel) -> AuditLog:
        return AuditLog(
            id=model.id,
            empresa_id=model.empresa_id,
            user_id=model.user_id,
            actor_label=None,
            module=model.module,
            action=model.action,
            level=model.level,
            description="Detalle cifrado",
            affected_table=model.tabla_afectada,
            record_id=model.registro_id,
            previous_data=None,
            new_data=None,
            source_ip=None,
            user_agent=None,
            created_at=model.fecha,
        )

    @staticmethod
    def _to_detail(model: AuditLogModel) -> AuditLog:
        if not model.datos_cifrados or not model.nonce_cifrado:
            payload = {
                "actor_label": model.actor_label,
                "description": model.description,
                "previous_data": model.datos_previos_jsonb,
                "new_data": model.datos_nuevos_jsonb,
                "source_ip": str(model.ip_origen) if model.ip_origen else None,
                "user_agent": model.user_agent,
            }
            integrity = None
        else:
            payload = AuditCipher(settings.app_audit_encryption_key).decrypt(
                model.datos_cifrados, model.nonce_cifrado, _metadata(model)
            )
            integrity = model.hash_registro == record_hash(
                model.hash_anterior, _metadata(model), model.nonce_cifrado, model.datos_cifrados
            )
        return AuditLog(
            id=model.id,
            empresa_id=model.empresa_id,
            user_id=model.user_id,
            actor_label=payload.get("actor_label"),
            module=model.module,
            action=model.action,
            level=model.level,
            description=payload.get("description") or "",
            affected_table=model.tabla_afectada,
            record_id=model.registro_id,
            previous_data=payload.get("previous_data"),
            new_data=payload.get("new_data"),
            source_ip=payload.get("source_ip"),
            user_agent=payload.get("user_agent"),
            created_at=model.fecha,
            integrity_verified=integrity,
        )
