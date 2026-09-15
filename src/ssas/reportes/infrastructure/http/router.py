import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from html import escape
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.api.openapi import TAG_REPORTES
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.infrastructure.database.session import get_session
from ssas.reportes.infrastructure.http.schemas import (
    ActualizarReporte,
    CrearReporte,
    EnviarReporteRequest,
    ReporteConfig,
    ReporteResponse,
    VistaPrevia,
)
from ssas.reportes.infrastructure.persistence.models.reporte import (
    ReporteDefinicionModel,
    ReporteEjecucionModel,
)

router = APIRouter(prefix="/reportes", tags=[TAG_REPORTES])

SOURCES = {
    "vacantes": {
        "titulo": "v.titulo", "estado": "v.estado", "modalidad": "v.modalidad",
        "ubicacion": "v.ubicacion", "cantidad_vacantes": "v.cantidad_vacantes",
        "fecha_publicacion": "v.fecha_publicacion",
    },
    "usuarios": {
        "nombres": "u.nombres", "apellidos": "u.apellidos", "email": "u.email",
        "username": "u.username", "telefono": "u.telefono", "activo": "u.activo",
        "ultimo_acceso": "u.ultimo_acceso",
    },
    "postulaciones": {
        "postulante": "concat(p.nombres, ' ', p.apellidos)", "email": "p.email",
        "vacante": "v.titulo", "estado": "po.estado", "puntaje": "po.puntaje_final",
        "fecha_postulacion": "po.fecha_postulacion",
    },
}
FROM_SQL = {
    "vacantes": "vacante v",
    "usuarios": "usuario u",
    "postulaciones": "postulacion po JOIN postulante p ON p.id=po.postulante_id JOIN vacante v ON v.id=po.vacante_id",
}
TENANT_COLUMN = {"vacantes": "v.empresa_id", "usuarios": "u.empresa_id", "postulaciones": "po.empresa_id"}


async def _audit(session: AsyncSession, request: Request, user: CurrentUser, empresa_id: str, action: str, description: str, record_id: str | None = None, new_data: dict | None = None) -> None:
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(
        empresa_id=empresa_id, user_id=user.id, module="REPORTES", action=action,
        description=description, affected_table="reporte_definicion", record_id=record_id,
        new_data=new_data, source_ip=get_client_ip(request), user_agent=request.headers.get("user-agent"),
    )


def _empresa(user: CurrentUser, requested: str | None) -> str:
    target = requested if user.es_plataforma else user.empresa_id
    if not target or (not user.es_plataforma and requested and requested != user.empresa_id):
        raise HTTPException(403, "Selecciona una empresa válida")
    return target


def _validate(config: ReporteConfig) -> dict[str, str]:
    columns = SOURCES.get(config.fuente)
    if not columns:
        raise HTTPException(422, "Fuente de reporte no permitida")
    referenced = set(config.columnas)
    referenced.update(item.campo for item in config.filtros)
    referenced.update(item.campo for item in config.orden)
    invalid = referenced - columns.keys()
    if invalid:
        raise HTTPException(422, f"Campos no permitidos: {', '.join(sorted(invalid))}")
    return columns


async def _rows(session: AsyncSession, empresa_id: str, config: ReporteConfig) -> list[dict]:
    columns = _validate(config)
    selected = ", ".join(f"{columns[name]} AS {name}" for name in config.columnas)
    clauses = [f"{TENANT_COLUMN[config.fuente]} = :empresa_id"]
    params: dict = {"empresa_id": empresa_id}
    for index, item in enumerate(config.filtros):
        expression = columns[item.campo]
        key = f"v{index}"
        if item.operador == "igual":
            clauses.append(f"{expression} = :{key}"); params[key] = item.valor
        elif item.operador == "contiene":
            clauses.append(f"CAST({expression} AS TEXT) ILIKE :{key}"); params[key] = f"%{item.valor}%"
        elif item.operador == "mayor_igual":
            clauses.append(f"{expression} >= :{key}"); params[key] = item.valor
        elif item.operador == "menor_igual":
            clauses.append(f"{expression} <= :{key}"); params[key] = item.valor
        elif item.operador == "entre" and isinstance(item.valor, list) and len(item.valor) == 2:
            clauses.append(f"{expression} BETWEEN :{key}a AND :{key}b")
            params[f"{key}a"], params[f"{key}b"] = item.valor
        else:
            raise HTTPException(422, "Valor de filtro inválido")
    order = ", ".join(f"{columns[o.campo]} {o.direccion.upper()}" for o in config.orden)
    sql = f"SELECT {selected} FROM {FROM_SQL[config.fuente]} WHERE {' AND '.join(clauses)}"
    if order: sql += f" ORDER BY {order}"
    sql += " LIMIT 5000"
    result = await session.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


def _serialize(model: ReporteDefinicionModel) -> ReporteResponse:
    return ReporteResponse.model_validate(model, from_attributes=True)


@router.get("/catalogo")
async def catalogo(_: CurrentUser = Depends(require_scoped_permission("reportes:ver", "platform:reportes:gestionar"))):
    """Lista las fuentes y columnas que pueden utilizarse sin aceptar SQL libre."""
    return [{"codigo": code, "nombre": code.replace("_", " ").title(), "columnas": list(cols)} for code, cols in SOURCES.items()]


@router.get("", response_model=list[ReporteResponse])
async def listar(empresa_id: str | None = None, user: CurrentUser = Depends(require_scoped_permission("reportes:ver", "platform:reportes:gestionar")), session: AsyncSession = Depends(get_session)):
    """Lista las definiciones de reportes guardadas dentro de la empresa autorizada."""
    result = await session.execute(select(ReporteDefinicionModel).where(ReporteDefinicionModel.empresa_id == _empresa(user, empresa_id)).order_by(ReporteDefinicionModel.nombre))
    return [_serialize(item) for item in result.scalars().all()]


@router.post("", response_model=ReporteResponse, status_code=201)
async def crear(body: CrearReporte, request: Request, empresa_id: str | None = None, user: CurrentUser = Depends(require_scoped_permission("reportes:crear", "platform:reportes:gestionar")), session: AsyncSession = Depends(get_session)):
    """Guarda una definición validada para reutilizar columnas, filtros y orden."""
    _validate(body)
    model = ReporteDefinicionModel(empresa_id=_empresa(user, empresa_id), usuario_id=user.id, **body.model_dump())
    session.add(model); await session.flush(); await session.refresh(model)
    await _audit(session, request, user, model.empresa_id, "CREATE", "Definición de reporte creada", model.id, {"nombre": model.nombre, "fuente": model.fuente})
    return _serialize(model)


@router.patch("/{report_id}", response_model=ReporteResponse)
async def actualizar(report_id: str, body: ActualizarReporte, empresa_id: str | None = None, user: CurrentUser = Depends(require_scoped_permission("reportes:editar", "platform:reportes:gestionar")), session: AsyncSession = Depends(get_session)):
    """Modifica o desactiva una definición perteneciente al alcance autorizado."""
    model = (await session.execute(select(ReporteDefinicionModel).where(ReporteDefinicionModel.id == report_id, ReporteDefinicionModel.empresa_id == _empresa(user, empresa_id)))).scalar_one_or_none()
    if not model: raise HTTPException(404, "Reporte no encontrado")
    for key, value in body.model_dump(exclude_unset=True).items(): setattr(model, key, value)
    _validate(ReporteConfig(fuente=model.fuente, columnas=model.columnas, filtros=model.filtros, orden=model.orden))
    await session.flush(); await session.refresh(model); return _serialize(model)


@router.post("/vista-previa", response_model=VistaPrevia)
async def vista_previa(body: ReporteConfig, empresa_id: str | None = None, page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=100), user: CurrentUser = Depends(require_scoped_permission("reportes:ejecutar", "platform:reportes:gestionar")), session: AsyncSession = Depends(get_session)):
    """Ejecuta una consulta limitada y devuelve una vista previa paginada."""
    rows = await _rows(session, _empresa(user, empresa_id), body); start = (page - 1) * per_page
    return VistaPrevia(columnas=body.columnas, items=rows[start:start + per_page], total=len(rows), page=page, per_page=per_page)


def _document(config: ReporteConfig, rows: list[dict], formato: str) -> tuple[bytes, str]:
    if formato == "html":
        head = "".join(f"<th>{escape(c)}</th>" for c in config.columnas)
        body = "".join("<tr>" + "".join(f"<td>{escape(str(row.get(c, '')))}</td>" for c in config.columnas) + "</tr>" for row in rows)
        return f"<!doctype html><meta charset='utf-8'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>".encode(), "text/html"
    if formato == "xlsx":
        book = Workbook(); sheet = book.active; sheet.append(config.columnas)
        for row in rows: sheet.append([row.get(c) for c in config.columnas])
        output = BytesIO(); book.save(output)
        return output.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if formato == "pdf":
        output = BytesIO(); canvas = Canvas(output, pagesize=landscape(A4)); y = 560
        canvas.setFont("Helvetica-Bold", 12); canvas.drawString(30, y, " | ".join(config.columnas)); y -= 20
        canvas.setFont("Helvetica", 8)
        for row in rows:
            if y < 30: canvas.showPage(); y = 560; canvas.setFont("Helvetica", 8)
            canvas.drawString(30, y, " | ".join(str(row.get(c, ""))[:35] for c in config.columnas)); y -= 13
        canvas.save(); return output.getvalue(), "application/pdf"
    raise HTTPException(422, "Formato no permitido")


@router.post("/exportar/{formato}")
async def exportar(formato: str, body: ReporteConfig, request: Request, empresa_id: str | None = None, user: CurrentUser = Depends(require_scoped_permission("reportes:exportar", "platform:reportes:gestionar")), session: AsyncSession = Depends(get_session)):
    """Genera y descarga el reporte en HTML, Excel o PDF y registra la ejecución."""
    target = _empresa(user, empresa_id); rows = await _rows(session, target, body)
    content, media = _document(body, rows, formato)
    session.add(ReporteEjecucionModel(empresa_id=target, usuario_id=user.id, formato=formato, filtros_aplicados=[f.model_dump() for f in body.filtros], estado="COMPLETADO", cantidad_registros=len(rows), fecha_fin=datetime.now(UTC)))
    await _audit(session, request, user, target, "EXPORT", "Reporte exportado", new_data={"formato": formato, "registros": len(rows)})
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="reporte.{formato}"'})


@router.post("/enviar", status_code=202)
async def enviar(body: EnviarReporteRequest, request: Request, empresa_id: str | None = None, user: CurrentUser = Depends(require_scoped_permission("reportes:enviar", "platform:reportes:gestionar")), session: AsyncSession = Depends(get_session)):
    """Genera el reporte y lo envía como adjunto mediante la configuración SMTP."""
    if not all((settings.smtp_host, settings.smtp_from_email)):
        raise HTTPException(503, "El envío de correo no está configurado")
    config = ReporteConfig(**body.model_dump(exclude={"destinatarios", "formato"})); target = _empresa(user, empresa_id)
    rows = await _rows(session, target, config); content, media = _document(config, rows, body.formato)
    message = EmailMessage(); message["Subject"] = "Reporte SSAH RRHH"; message["From"] = settings.smtp_from_email; message["To"] = ", ".join(body.destinatarios); message.set_content("Se adjunta el reporte solicitado.")
    main, sub = media.split("/", 1); message.add_attachment(content, maintype=main, subtype=sub, filename=f"reporte.{body.formato}")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        if settings.smtp_use_tls: smtp.starttls()
        if settings.smtp_username: smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)
    session.add(ReporteEjecucionModel(empresa_id=target, usuario_id=user.id, formato=body.formato, filtros_aplicados=[f.model_dump() for f in body.filtros], estado="COMPLETADO", cantidad_registros=len(rows), fecha_fin=datetime.now(UTC)))
    await _audit(session, request, user, target, "SEND", "Reporte enviado por correo", new_data={"formato": body.formato, "destinatarios": len(body.destinatarios)})
    return {"message": "Reporte enviado"}
