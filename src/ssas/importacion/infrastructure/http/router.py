import io

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.importacion.application.catalogos import CATALOGS, ImportErrorDetail, apply, preview
from ssas.importacion.application.empleados import apply_employees, preview_employees
from ssas.importacion.application.usuarios import apply_users, preview_users
from ssas.infrastructure.database.session import get_session
from ssas.postulaciones.infrastructure.http.tablero_router import _empresa
from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)
from ssas.suscripciones.application.policy import SubscriptionPolicy, SubscriptionPolicyError
from ssas.suscripciones.infrastructure.http.feature_guard import require_plan_feature

router = APIRouter(prefix="/importaciones", tags=["Importación"])
guard = require_scoped_permission("importacion:gestionar", "platform:importacion:gestionar")


def kind_or_404(kind: str) -> tuple:
    if kind not in CATALOGS:
        raise HTTPException(404, "Catálogo no admitido")
    return CATALOGS[kind]


def validate_file(archivo: UploadFile) -> None:
    if not archivo.filename or not archivo.filename.lower().endswith((".csv", ".xlsx")):
        raise HTTPException(422, "Selecciona un archivo .csv o .xlsx")
    if archivo.content_type not in (
        None,
        "",
        "text/csv",
        "text/plain",
        "application/csv",
        "application/vnd.ms-excel",
        "application/octet-stream",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        raise HTTPException(422, "El archivo debe ser CSV o Excel")


async def authorize_users(kind: str, user: CurrentUser, session: AsyncSession) -> None:
    if kind != "usuarios":
        return
    codes = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
        user.id, user.empresa_id
    )
    required = "platform:usuarios:gestionar" if user.es_plataforma else "usuarios:crear"
    if required not in codes:
        raise HTTPException(403, "No tienes permiso para importar usuarios")


async def authorize_sensitive(kind: str, user: CurrentUser, session: AsyncSession) -> None:
    await authorize_users(kind, user, session)
    if kind != "empleados":
        return
    codes = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
        user.id, user.empresa_id
    )
    required = "platform:empleados:importar" if user.es_plataforma else "empleados:importar"
    if required not in codes:
        raise HTTPException(403, "No tienes permiso para importar empleados")


@router.get("/{kind}/plantilla")
async def plantilla(kind: str, formato: str = Query("csv", pattern="^(csv|xlsx)$"), user: CurrentUser = Depends(guard), session: AsyncSession = Depends(get_session)):
    _, columns = kind_or_404(kind)
    await authorize_sensitive(kind, user, session)
    version = "2" if kind == "etapas" else "1"
    if formato == "xlsx":
        workbook = Workbook()
        workbook.active.title = "Datos"
        workbook.active.append(list(columns))
        output = io.BytesIO()
        workbook.save(output)
        return Response(
            output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{kind}.xlsx"',
                     "X-Template-Version": version},
        )
    return Response(
        ",".join(columns) + "\n",
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{kind}.csv"',
                 "X-Template-Version": version},
    )


@router.post("/{kind}/previsualizar")
async def previsualizar(
    kind: str,
    archivo: UploadFile = File(...),
    empresa_id: str | None = Query(None),
    user: CurrentUser = Depends(guard),
    session: AsyncSession = Depends(get_session),
):
    kind_or_404(kind)
    validate_file(archivo)
    target = _empresa(user, empresa_id)
    await require_plan_feature(session, target, "importacion_masiva")
    await authorize_sensitive(kind, user, session)
    content = await archivo.read(1_000_001)
    try:
        if kind == "usuarios":
            return await preview_users(session, target, content, archivo.filename)
        if kind == "empleados":
            return await preview_employees(session, target, content, archivo.filename)
        return await preview(session, target, kind, content, archivo.filename)
    except ImportErrorDetail as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/{kind}/confirmar")
async def confirmar(
    kind: str,
    request: Request,
    archivo: UploadFile = File(...),
    sha256: str = Form(..., min_length=64, max_length=64),
    empresa_id: str | None = Query(None),
    user: CurrentUser = Depends(guard),
    session: AsyncSession = Depends(get_session),
):
    kind_or_404(kind)
    validate_file(archivo)
    target = _empresa(user, empresa_id)
    await require_plan_feature(session, target, "importacion_masiva")
    await authorize_sensitive(kind, user, session)
    content = await archivo.read(1_000_001)
    try:
        if not user.es_plataforma:
            await SubscriptionPolicy(session, settings.subscription_grace_days).require_operational(
                target
            )
        if kind == "usuarios":
            result = await preview_users(session, target, content, archivo.filename)
            if result["sha256"] != sha256:
                raise ImportErrorDetail("El archivo cambió desde la vista previa")
            if result["errores"]:
                raise ImportErrorDetail("Corrige las filas marcadas antes de importar")
            plan = await SubscriptionPolicy(session, settings.subscription_grace_days).require_operational(target)
            active = await session.scalar(select(func.count(UserModel.id)).where(
                UserModel.empresa_id == target, UserModel.is_active.is_(True),
                UserModel.eliminado_at.is_(None),
            ))
            if (active or 0) + result["crear"] > plan.max_usuarios:
                raise SubscriptionPolicyError("La importación supera el límite de usuarios del plan")
            result = await apply_users(session, target, content, archivo.filename, sha256)
        elif kind == "empleados":
            result = await apply_employees(session, target, content, archivo.filename, sha256)
        else:
            result = await apply(session, target, kind, content, sha256, archivo.filename)
        await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
            empresa_id=target,
            user_id=user.id,
            module="USUARIOS" if kind == "usuarios" else "ORGANIZACION",
            action="IMPORT",
            description=f"Importación de {kind} confirmada",
            affected_table="empleado" if kind == "empleados" else kind,
            source_ip=get_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            new_data={
                "tipo": kind,
                "sha256": sha256,
                "creados": result["crear"],
                "omitidos": result["omitir"],
            },
        )
        await session.flush()
        return result
    except ImportErrorDetail as exc:
        raise HTTPException(422, str(exc)) from exc
    except SubscriptionPolicyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(409, "Los datos cambiaron; vuelve a previsualizar") from exc


for route in router.routes:
    route.description = "Operación de importación CSV/Excel limitada a la empresa autorizada."
