from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.dto.audit_log_filter import AuditLogFilter
from ssas.bitacora.application.use_cases.get_audit_log import GetAuditLog
from ssas.bitacora.application.use_cases.list_audit_logs import ListAuditLogs
from ssas.bitacora.domain.exceptions import AuditLogNotFoundError
from ssas.bitacora.infrastructure.crypto import AuditEncryptionError
from ssas.bitacora.infrastructure.http.schemas import (
    AuditIntegritySchema,
    AuditLogPageSchema,
    AuditLogSchema,
)
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.core.api.openapi import (
    AUTHENTICATED_RESPONSES,
    EMPRESA_SCOPE_DESCRIPTION,
    TAG_AUDIT,
)
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.infrastructure.database.session import get_session

router = APIRouter(prefix="/bitacora", tags=[TAG_AUDIT], responses=AUTHENTICATED_RESPONSES)


def _target_empresa(current_user: CurrentUser, requested: str | None) -> str | None:
    if current_user.es_plataforma:
        return requested
    if requested is not None and requested != current_user.empresa_id:
        raise HTTPException(status_code=403, detail="No puedes consultar otra empresa")
    return current_user.empresa_id


@router.get(
    "",
    response_model=AuditLogPageSchema,
    summary="Consultar eventos de bitácora",
    description=(
        "Lista eventos inmutables con filtros por actor, módulo, acción y fechas. Un usuario "
        "empresarial solo consulta su empresa; plataforma puede seleccionar una empresa. "
        "Permisos: `bitacora:ver` o `platform:bitacora:ver`."
    ),
    responses={404: {"description": "Evento no encontrado dentro del alcance."}},
)
async def list_audit_logs(
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    user_id: str | None = Query(
        default=None, description="Filtra por usuario que originó el evento."
    ),
    module: str | None = Query(default=None, description="Filtra por módulo funcional."),
    action: str | None = Query(default=None, description="Filtra por código de acción."),
    level: str | None = Query(default=None, description="Filtra por nivel del evento."),
    affected_table: str | None = Query(default=None, description="Filtra por tabla afectada."),
    record_id: str | None = Query(default=None, description="Filtra por registro afectado."),
    start_date: datetime | None = Query(
        default=None, description="Fecha y hora inicial, inclusiva."
    ),
    end_date: datetime | None = Query(default=None, description="Fecha y hora final, inclusiva."),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    current_user: CurrentUser = Depends(
        require_scoped_permission("bitacora:ver", "platform:bitacora:ver")
    ),
    session: AsyncSession = Depends(get_session),
):
    filters = AuditLogFilter(
        empresa_id=_target_empresa(current_user, empresa_id),
        user_id=user_id,
        module=module,
        action=action,
        level=level,
        affected_table=affected_table,
        record_id=record_id,
        start_date=start_date,
        end_date=end_date,
        page=page,
        per_page=per_page,
    )
    return await ListAuditLogs(SqlAlchemyAuditLogRepository(session)).execute(filters)


@router.get(
    "/integridad",
    response_model=AuditIntegritySchema,
    summary="Verificar integridad de la bitácora",
    description=(
        "Recorre la cadena de hashes del alcance autorizado y señala el primer evento "
        "alterado o ausente, sin descifrar ni exponer su contenido."
    ),
)
async def verify_audit_integrity(
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("bitacora:ver_detalle", "platform:bitacora:ver_detalle")
    ),
    session: AsyncSession = Depends(get_session),
):
    valid, invalid_id, checked = await SqlAlchemyAuditLogRepository(session).verify_chain(
        _target_empresa(current_user, empresa_id)
    )
    return AuditIntegritySchema(
        valid=valid, checked_records=checked, first_invalid_id=invalid_id
    )


@router.get(
    "/exportar-cifrada",
    summary="Exportar archivo confidencial de bitácora",
    description=(
        "Descarga los eventos como JSON Lines con sobres AES-GCM y hashes de integridad. "
        "El archivo no contiene la llave ni detalles en texto claro."
    ),
    response_class=Response,
)
async def export_encrypted_audit(
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission("bitacora:exportar", "platform:bitacora:exportar")
    ),
    session: AsyncSession = Depends(get_session),
):
    target = _target_empresa(current_user, empresa_id)
    content = await SqlAlchemyAuditLogRepository(session).encrypted_export(
        AuditLogFilter(empresa_id=target, page=1, per_page=200)
    )
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": 'attachment; filename="bitacora.jsonl.enc"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{audit_log_id}",
    response_model=AuditLogSchema,
    summary="Consultar detalle de un evento",
    description=(
        "Obtiene un evento específico con su contexto, datos anteriores y datos nuevos, "
        "respetando el alcance de empresa."
    ),
)
async def get_audit_log(
    audit_log_id: str,
    empresa_id: str | None = Query(default=None, description=EMPRESA_SCOPE_DESCRIPTION),
    current_user: CurrentUser = Depends(
        require_scoped_permission(
            "bitacora:ver_detalle", "platform:bitacora:ver_detalle"
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await GetAuditLog(SqlAlchemyAuditLogRepository(session)).execute(
            audit_log_id,
            _target_empresa(current_user, empresa_id),
        )
    except AuditLogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AuditEncryptionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
