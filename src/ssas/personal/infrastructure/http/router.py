"""Employee records, contracts, attendance and absence operations."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.cargos.infrastructure.persistence.models.cargo import CargoModel
from ssas.config.settings import settings
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.departamentos.infrastructure.persistence.models.departamento import DepartamentoModel
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import get_session
from ssas.personal.application.attendance import minutes_late, worked_hours
from ssas.personal.application.audit import record_personal_event
from ssas.personal.infrastructure.persistence.models import (
    AsistenciaModel,
    BoletaPagoModel,
    ContratoModel,
    DocumentoEmpleadoModel,
    PeriodoNominaModel,
    SaldoVacacionModel,
    SolicitudAusenciaModel,
    TipoAusenciaModel,
)

router = APIRouter(prefix="/personal", tags=["Personal"])


class ContractInput(BaseModel):
    numero_contrato: str = Field(min_length=1, max_length=80)
    cargo_id: UUID
    departamento_id: UUID
    jefe_directo_id: UUID | None = None
    tipo_contrato: str = Field(min_length=1, max_length=30)
    modalidad: str = Field(min_length=1, max_length=30)
    jornada: str = Field(min_length=1, max_length=30)
    hora_entrada_programada: time
    horas_jornada: Decimal = Field(gt=0, le=24)
    minutos_descanso: int = Field(ge=0, le=240)
    salario_basico: Decimal = Field(gt=0)
    fecha_inicio: date
    fecha_fin: date | None = None
    motivo_cambio: str | None = None


class GPSInput(BaseModel):
    latitud: Decimal = Field(ge=-90, le=90)
    longitud: Decimal = Field(ge=-180, le=180)


class AbsenceInput(BaseModel):
    tipo_ausencia_id: UUID
    fecha_inicio: date
    fecha_fin: date
    motivo: str = Field(min_length=1)
    documento_id: UUID | None = None


class AbsenceDecision(BaseModel):
    aprobar: bool
    observacion: str | None = None
    dias_habiles_vacacion: int | None = Field(default=None, ge=1, le=366)


class VacationBalanceInput(BaseModel):
    gestion: int = Field(ge=2000, le=2100)
    dias_asignados: int = Field(ge=0, le=365)


def tenant(user: CurrentUser, empresa_id: UUID | None) -> str:
    if user.empresa_id:
        if empresa_id is not None and str(empresa_id) != user.empresa_id:
            raise HTTPException(403, "No puedes operar sobre otra empresa")
        return user.empresa_id
    if empresa_id is None:
        raise HTTPException(422, "empresa_id es obligatorio para plataforma")
    return str(empresa_id)


async def employee(session: AsyncSession, company: str, employee_id: str) -> EmpleadoModel:
    row = await session.scalar(
        select(EmpleadoModel).where(
            EmpleadoModel.id == employee_id, EmpleadoModel.empresa_id == company
        )
    )
    if row is None:
        raise HTTPException(404, "Empleado no encontrado")
    return row


async def self_employee(session: AsyncSession, user: CurrentUser) -> EmpleadoModel:
    if not user.empresa_id:
        raise HTTPException(403, "Se requiere una cuenta de empresa")
    row = await session.scalar(
        select(EmpleadoModel).where(
            EmpleadoModel.usuario_id == user.id, EmpleadoModel.empresa_id == user.empresa_id
        )
    )
    if row is None:
        raise HTTPException(404, "La cuenta no esta asociada a un empleado")
    return row


@router.get("/empleados/{empleado_id}/documentos", summary="Consultar documentos del legajo")
async def list_documents(
    empleado_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("personal:ver", "platform:personal:ver")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    await employee(session, company, str(empleado_id))
    rows = (
        await session.scalars(
            select(DocumentoEmpleadoModel)
            .where(
                DocumentoEmpleadoModel.empresa_id == company,
                DocumentoEmpleadoModel.empleado_id == str(empleado_id),
            )
            .order_by(DocumentoEmpleadoModel.fecha_carga.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "tipo": r.tipo,
            "nombre": r.nombre,
            "tamano_bytes": r.tamano_bytes,
            "fecha_carga": r.fecha_carga,
        }
        for r in rows
    ]


async def _store_document(
    session: AsyncSession,
    user: CurrentUser,
    company: str,
    empleado_id: str,
    tipo: str,
    archivo: UploadFile,
) -> dict:
    if (
        not tipo
        or len(tipo) > 30
        or archivo.content_type not in {"application/pdf", "image/jpeg", "image/png"}
    ):
        raise HTTPException(422, "Tipo o formato no admitido")
    data = await archivo.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Documento vacio o mayor a 10 MB")
    signatures = {
        "application/pdf": b"%PDF-",
        "image/jpeg": b"\xff\xd8\xff",
        "image/png": b"\x89PNG\r\n\x1a\n",
    }
    if not data.startswith(signatures[archivo.content_type]):
        raise HTTPException(422, "El contenido no coincide con el formato")
    suffixes = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}
    suffix = suffixes[archivo.content_type]
    root = Path(settings.employee_files_directory).resolve()
    destination = root / company / str(empleado_id)
    destination.mkdir(parents=True, exist_ok=True)
    stored = destination / f"{uuid4()}{suffix}"
    stored.write_bytes(data)
    row = DocumentoEmpleadoModel(
        empresa_id=company,
        empleado_id=str(empleado_id),
        tipo=tipo,
        nombre=f"{Path(archivo.filename or 'documento').stem[:190]}{suffix}",
        ruta_privada=str(stored),
        tipo_mime=archivo.content_type,
        tamano_bytes=len(data),
    )
    session.add(row)
    await session.flush()
    await record_personal_event(
        session,
        user,
        company,
        action="DOCUMENTO_EMPLEADO_CREADO",
        table="documento_empleado",
        record_id=row.id,
        data={"empleado_id": row.empleado_id, "tipo": row.tipo},
    )
    return {"id": row.id, "nombre": row.nombre, "tamano_bytes": row.tamano_bytes}


@router.post(
    "/empleados/{empleado_id}/documentos",
    status_code=201,
    summary="Agregar documento privado al legajo",
)
async def upload_document(
    empleado_id: UUID,
    tipo: str,
    archivo: UploadFile = File(...),
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("personal:gestionar", "platform:personal:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    await employee(session, company, str(empleado_id))
    return await _store_document(session, user, company, str(empleado_id), tipo, archivo)


@router.post("/mi/documentos", status_code=201, summary="Agregar comprobante a mi legajo")
async def upload_own_document(
    archivo: UploadFile = File(...),
    user: CurrentUser = Depends(require_scoped_permission("personal:mi", "platform:personal:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    return await _store_document(
        session, user, user.empresa_id, worker.id, "LICENCIA_MEDICA", archivo
    )


@router.get(
    "/empleados/{empleado_id}/documentos/{documento_id}/descarga",
    summary="Descargar documento del legajo",
)
async def download_document(
    empleado_id: UUID,
    documento_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("personal:ver", "platform:personal:ver")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    row = await session.scalar(
        select(DocumentoEmpleadoModel).where(
            DocumentoEmpleadoModel.id == str(documento_id),
            DocumentoEmpleadoModel.empresa_id == company,
            DocumentoEmpleadoModel.empleado_id == str(empleado_id),
        )
    )
    if row is None:
        raise HTTPException(404, "Documento no encontrado")
    root = Path(settings.employee_files_directory).resolve()
    file_path = Path(row.ruta_privada).resolve()
    if not file_path.is_relative_to(root / company) or not file_path.is_file():
        raise HTTPException(404, "Archivo privado no disponible")
    return FileResponse(file_path, media_type=row.tipo_mime, filename=row.nombre)


def contract_dict(row: ContratoModel) -> dict:
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "empresa_id",
            "empleado_id",
            "cargo_id",
            "departamento_id",
            "jefe_directo_id",
            "contrato_anterior_id",
            "numero_contrato",
            "tipo_contrato",
            "modalidad",
            "jornada",
            "hora_entrada_programada",
            "horas_jornada",
            "minutos_descanso",
            "salario_basico",
            "moneda",
            "fecha_inicio",
            "fecha_fin",
            "motivo_cambio",
            "estado",
            "creado_en",
        )
    }


@router.get("/empleados/{empleado_id}/contratos", summary="Consultar historial de contratos")
async def contracts(
    empleado_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("personal:ver", "platform:personal:ver")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    await employee(session, company, str(empleado_id))
    rows = (
        await session.scalars(
            select(ContratoModel)
            .where(
                ContratoModel.empresa_id == company, ContratoModel.empleado_id == str(empleado_id)
            )
            .order_by(ContratoModel.fecha_inicio.desc())
        )
    ).all()
    return [contract_dict(row) for row in rows]


@router.get("/mi/contratos", summary="Consultar mis contratos")
async def my_contracts(
    user: CurrentUser = Depends(require_scoped_permission("personal:mi", "platform:personal:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    rows = (
        await session.scalars(
            select(ContratoModel)
            .where(
                ContratoModel.empresa_id == user.empresa_id,
                ContratoModel.empleado_id == worker.id,
            )
            .order_by(ContratoModel.fecha_inicio.desc())
        )
    ).all()
    return [contract_dict(row) for row in rows]


@router.get("/mi/documentos", summary="Consultar mi legajo")
async def my_documents(
    user: CurrentUser = Depends(require_scoped_permission("personal:mi", "platform:personal:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    rows = (
        await session.scalars(
            select(DocumentoEmpleadoModel)
            .where(
                DocumentoEmpleadoModel.empresa_id == user.empresa_id,
                DocumentoEmpleadoModel.empleado_id == worker.id,
            )
            .order_by(DocumentoEmpleadoModel.fecha_carga.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "tipo": r.tipo,
            "nombre": r.nombre,
            "tamano_bytes": r.tamano_bytes,
            "fecha_carga": r.fecha_carga,
        }
        for r in rows
    ]


@router.get("/mi/documentos/{documento_id}/descarga", summary="Descargar documento propio")
async def download_own_document(
    documento_id: UUID,
    user: CurrentUser = Depends(require_scoped_permission("personal:mi", "platform:personal:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    row = await session.scalar(
        select(DocumentoEmpleadoModel).where(
            DocumentoEmpleadoModel.id == str(documento_id),
            DocumentoEmpleadoModel.empresa_id == user.empresa_id,
            DocumentoEmpleadoModel.empleado_id == worker.id,
        )
    )
    if row is None:
        raise HTTPException(404, "Documento no encontrado")
    root = Path(settings.employee_files_directory).resolve()
    file_path = Path(row.ruta_privada).resolve()
    if not file_path.is_relative_to(root / user.empresa_id) or not file_path.is_file():
        raise HTTPException(404, "Archivo privado no disponible")
    return FileResponse(file_path, media_type=row.tipo_mime, filename=row.nombre)


@router.put(
    "/empleados/{empleado_id}/vacaciones/{gestion}", summary="Asignar saldo anual de vacaciones"
)
async def assign_vacation_balance(
    empleado_id: UUID,
    gestion: int,
    payload: VacationBalanceInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("ausencias:gestionar", "platform:ausencias:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    await employee(session, company, str(empleado_id))
    if gestion != payload.gestion:
        raise HTTPException(422, "La gestion no coincide")
    row = await session.scalar(
        select(SaldoVacacionModel)
        .where(
            SaldoVacacionModel.empresa_id == company,
            SaldoVacacionModel.empleado_id == str(empleado_id),
            SaldoVacacionModel.gestion == gestion,
        )
        .with_for_update()
    )
    if row is None:
        row = SaldoVacacionModel(
            empresa_id=company,
            empleado_id=str(empleado_id),
            gestion=gestion,
            dias_asignados=payload.dias_asignados,
        )
        session.add(row)
    elif payload.dias_asignados < row.dias_usados:
        raise HTTPException(409, "No se puede reducir el saldo por debajo de lo ya utilizado")
    else:
        row.dias_asignados = payload.dias_asignados
    await session.flush()
    await record_personal_event(
        session,
        user,
        company,
        action="SALDO_VACACION_ASIGNADO",
        table="saldo_vacacion",
        record_id=row.id,
        data={"gestion": gestion, "dias_asignados": row.dias_asignados},
    )
    return {
        "gestion": gestion,
        "dias_asignados": row.dias_asignados,
        "dias_usados": row.dias_usados,
    }


@router.post(
    "/empleados/{empleado_id}/contratos",
    status_code=201,
    summary="Registrar nueva version de contrato",
)
async def create_contract(
    empleado_id: UUID,
    payload: ContractInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("personal:gestionar", "platform:personal:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    target = await session.scalar(
        select(EmpleadoModel)
        .where(EmpleadoModel.id == str(empleado_id), EmpleadoModel.empresa_id == company)
        .with_for_update()
    )
    if target is None:
        raise HTTPException(404, "Empleado no encontrado")
    if target.estado != "ACTIVO" or payload.fecha_inicio < target.fecha_ingreso:
        raise HTTPException(409, "El empleado debe estar activo y la fecha debe ser valida")
    if payload.fecha_fin and payload.fecha_fin < payload.fecha_inicio:
        raise HTTPException(422, "La fecha final precede el inicio")
    cargo = await session.scalar(
        select(CargoModel).where(
            CargoModel.id == str(payload.cargo_id), CargoModel.empresa_id == company
        )
    )
    department = await session.scalar(
        select(DepartamentoModel).where(
            DepartamentoModel.id == str(payload.departamento_id),
            DepartamentoModel.empresa_id == company,
        )
    )
    if not cargo or not department or cargo.departamento_id not in (None, department.id):
        raise HTTPException(422, "Cargo y departamento deben pertenecer a la misma empresa")
    if payload.jefe_directo_id:
        await employee(session, company, str(payload.jefe_directo_id))
        if str(payload.jefe_directo_id) == str(empleado_id):
            raise HTTPException(422, "El empleado no puede ser su propio jefe")
    current = await session.scalar(
        select(ContratoModel)
        .where(
            ContratoModel.empresa_id == company,
            ContratoModel.empleado_id == str(empleado_id),
            ContratoModel.estado == "VIGENTE",
        )
        .with_for_update()
    )
    if current and payload.fecha_inicio <= current.fecha_inicio:
        raise HTTPException(409, "La nueva version debe comenzar despues de la anterior")
    paid = await session.scalar(
        select(BoletaPagoModel.id)
        .join(PeriodoNominaModel, PeriodoNominaModel.id == BoletaPagoModel.periodo_id)
        .where(
            BoletaPagoModel.empresa_id == company,
            BoletaPagoModel.empleado_id == str(empleado_id),
            PeriodoNominaModel.empresa_id == company,
            PeriodoNominaModel.estado == "APROBADO",
            or_(
                PeriodoNominaModel.gestion > payload.fecha_inicio.year,
                and_(
                    PeriodoNominaModel.gestion == payload.fecha_inicio.year,
                    PeriodoNominaModel.mes >= payload.fecha_inicio.month,
                ),
            ),
        )
    )
    if paid:
        raise HTTPException(409, "No se puede alterar un periodo con nomina aprobada")
    if current:
        current.fecha_fin = payload.fecha_inicio - timedelta(days=1)
        current.estado = "REEMPLAZADO"
        await session.flush()
    row = ContratoModel(
        empresa_id=company,
        empleado_id=str(empleado_id),
        cargo_id=str(payload.cargo_id),
        departamento_id=str(payload.departamento_id),
        jefe_directo_id=str(payload.jefe_directo_id) if payload.jefe_directo_id else None,
        contrato_anterior_id=current.id if current else None,
        numero_contrato=payload.numero_contrato,
        tipo_contrato=payload.tipo_contrato,
        modalidad=payload.modalidad,
        jornada=payload.jornada,
        hora_entrada_programada=payload.hora_entrada_programada,
        horas_jornada=payload.horas_jornada,
        minutos_descanso=payload.minutos_descanso,
        salario_basico=payload.salario_basico,
        fecha_inicio=payload.fecha_inicio,
        fecha_fin=payload.fecha_fin,
        motivo_cambio=payload.motivo_cambio,
        estado="VIGENTE"
        if payload.fecha_fin is None or payload.fecha_fin >= datetime.now(UTC).date()
        else "VENCIDO",
    )
    session.add(row)
    await session.flush()
    await record_personal_event(
        session,
        user,
        company,
        action="CONTRATO_CREADO",
        table="contrato",
        record_id=row.id,
        data={"empleado_id": row.empleado_id, "fecha_inicio": str(row.fecha_inicio)},
    )
    return contract_dict(row)


@router.get("/tipos-ausencia", summary="Consultar tipos de ausencia")
async def absence_types(
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("ausencias:mi", "platform:ausencias:mi")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    rows = (
        await session.scalars(
            select(TipoAusenciaModel).where(
                TipoAusenciaModel.empresa_id == company, TipoAusenciaModel.activo.is_(True)
            )
        )
    ).all()
    return [
        {
            "id": row.id,
            "codigo": row.codigo,
            "nombre": row.nombre,
            "es_remunerado": row.es_remunerado,
            "descuenta_vacacion": row.descuenta_vacacion,
        }
        for row in rows
    ]


@router.post("/mi/asistencia/entrada", status_code=201, summary="Marcar entrada con GPS")
async def clock_in(
    payload: GPSInput,
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:marcar", "platform:asistencia:marcar")
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    now = datetime.now(UTC)
    local_date = now.astimezone(ZoneInfo("America/La_Paz")).date()
    active = await session.scalar(
        select(ContratoModel).where(
            ContratoModel.empresa_id == user.empresa_id,
            ContratoModel.empleado_id == worker.id,
            ContratoModel.fecha_inicio <= local_date,
            or_(ContratoModel.fecha_fin.is_(None), ContratoModel.fecha_fin >= local_date),
            ContratoModel.estado == "VIGENTE",
        )
    )
    if not active:
        raise HTTPException(409, "No hay contrato vigente para este dia")
    existing = await session.scalar(
        select(AsistenciaModel.id).where(
            AsistenciaModel.empresa_id == user.empresa_id,
            AsistenciaModel.empleado_id == worker.id,
            AsistenciaModel.fecha == local_date,
        )
    )
    if existing:
        raise HTTPException(409, "La entrada de hoy ya fue registrada")
    row = AsistenciaModel(
        empresa_id=user.empresa_id,
        empleado_id=worker.id,
        fecha=local_date,
        hora_entrada=now,
        lat_entrada=payload.latitud,
        lon_entrada=payload.longitud,
        minutos_retraso=minutes_late(
            now.astimezone(ZoneInfo("America/La_Paz")), active.hora_entrada_programada
        ),
        origen="MOVIL",
    )
    session.add(row)
    await session.flush()
    return {
        "id": row.id,
        "fecha": row.fecha,
        "hora_entrada": row.hora_entrada,
        "minutos_retraso": row.minutos_retraso,
    }


@router.post("/mi/asistencia/salida", summary="Marcar salida con GPS")
async def clock_out(
    payload: GPSInput,
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:marcar", "platform:asistencia:marcar")
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    now = datetime.now(UTC)
    row = await session.scalar(
        select(AsistenciaModel)
        .where(
            AsistenciaModel.empresa_id == user.empresa_id,
            AsistenciaModel.empleado_id == worker.id,
            AsistenciaModel.hora_salida.is_(None),
            AsistenciaModel.hora_entrada >= now - timedelta(hours=24),
        )
        .order_by(AsistenciaModel.hora_entrada.desc())
        .with_for_update()
    )
    if row is None or row.hora_salida is not None:
        raise HTTPException(409, "No hay entrada abierta hoy")
    contract = await session.scalar(
        select(ContratoModel)
        .where(
            ContratoModel.empresa_id == user.empresa_id,
            ContratoModel.empleado_id == worker.id,
            ContratoModel.fecha_inicio <= row.fecha,
            or_(ContratoModel.fecha_fin.is_(None), ContratoModel.fecha_fin >= row.fecha),
        )
        .order_by(ContratoModel.fecha_inicio.desc())
    )
    if contract is None:
        raise HTTPException(409, "No hay contrato para el fichaje")
    try:
        worked, overtime = worked_hours(
            row.hora_entrada, now, contract.minutos_descanso, contract.horas_jornada
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    row.hora_salida = now
    row.lat_salida = payload.latitud
    row.lon_salida = payload.longitud
    row.horas_trabajadas = worked
    row.horas_extra = overtime
    return {
        "id": row.id,
        "hora_salida": row.hora_salida,
        "horas_trabajadas": worked,
        "horas_extra": overtime,
    }


@router.get("/mi/asistencia", summary="Consultar mis asistencias")
async def my_attendance(
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:mi", "platform:asistencia:mi")
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    rows = (
        await session.scalars(
            select(AsistenciaModel)
            .where(
                AsistenciaModel.empresa_id == user.empresa_id,
                AsistenciaModel.empleado_id == worker.id,
            )
            .order_by(AsistenciaModel.fecha.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": r.id,
            "fecha": r.fecha,
            "hora_entrada": r.hora_entrada,
            "hora_salida": r.hora_salida,
            "horas_trabajadas": r.horas_trabajadas,
            "minutos_retraso": r.minutos_retraso,
        }
        for r in rows
    ]


@router.get("/asistencias", summary="Consultar asistencia de la empresa")
async def company_attendance(
    empresa_id: UUID | None = None,
    empleado_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:ver", "platform:asistencia:ver")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    query = select(AsistenciaModel).where(AsistenciaModel.empresa_id == company)
    if empleado_id:
        await employee(session, company, str(empleado_id))
        query = query.where(AsistenciaModel.empleado_id == str(empleado_id))
    rows = (await session.scalars(query.order_by(AsistenciaModel.fecha.desc()).limit(100))).all()
    return [
        {
            "id": r.id,
            "empleado_id": r.empleado_id,
            "fecha": r.fecha,
            "hora_entrada": r.hora_entrada,
            "hora_salida": r.hora_salida,
            "horas_trabajadas": r.horas_trabajadas,
        }
        for r in rows
    ]


@router.get("/mi/equipo/asistencias", summary="Consultar asistencia de mi equipo")
async def team_attendance(
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:ver_equipo", "platform:asistencia:ver_equipo")
    ),
    session: AsyncSession = Depends(get_session),
):
    leader = await self_employee(session, user)
    team = select(ContratoModel.empleado_id).where(
        ContratoModel.empresa_id == user.empresa_id,
        ContratoModel.jefe_directo_id == leader.id,
        ContratoModel.estado == "VIGENTE",
    )
    rows = (
        await session.scalars(
            select(AsistenciaModel)
            .where(
                AsistenciaModel.empresa_id == user.empresa_id,
                AsistenciaModel.empleado_id.in_(team),
            )
            .order_by(AsistenciaModel.fecha.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": r.id,
            "empleado_id": r.empleado_id,
            "fecha": r.fecha,
            "hora_entrada": r.hora_entrada,
            "hora_salida": r.hora_salida,
            "horas_trabajadas": r.horas_trabajadas,
        }
        for r in rows
    ]


@router.post("/mi/ausencias", status_code=201, summary="Solicitar ausencia")
async def request_absence(
    payload: AbsenceInput,
    user: CurrentUser = Depends(
        require_scoped_permission("ausencias:solicitar", "platform:ausencias:solicitar")
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    days = (payload.fecha_fin - payload.fecha_inicio).days + 1
    if days <= 0 or days > 366:
        raise HTTPException(422, "Rango de fechas invalido")
    if (
        worker.estado != "ACTIVO"
        or payload.fecha_inicio < worker.fecha_ingreso
        or worker.fecha_salida
        and payload.fecha_fin > worker.fecha_salida
    ):
        raise HTTPException(409, "La ausencia debe estar dentro de la relacion laboral activa")
    kind = await session.scalar(
        select(TipoAusenciaModel).where(
            TipoAusenciaModel.id == str(payload.tipo_ausencia_id),
            TipoAusenciaModel.empresa_id == user.empresa_id,
            TipoAusenciaModel.activo.is_(True),
        )
    )
    if kind is None or (kind.requiere_documento and not payload.documento_id):
        raise HTTPException(422, "Tipo de ausencia o documento invalido")
    if payload.documento_id:
        document = await session.scalar(
            select(DocumentoEmpleadoModel.id).where(
                DocumentoEmpleadoModel.id == str(payload.documento_id),
                DocumentoEmpleadoModel.empresa_id == user.empresa_id,
                DocumentoEmpleadoModel.empleado_id == worker.id,
            )
        )
        if document is None:
            raise HTTPException(422, "El documento no pertenece al legajo del empleado")
    overlapping = await session.scalar(
        select(SolicitudAusenciaModel.id).where(
            SolicitudAusenciaModel.empresa_id == user.empresa_id,
            SolicitudAusenciaModel.empleado_id == worker.id,
            SolicitudAusenciaModel.estado.in_(("PENDIENTE", "APROBADA")),
            SolicitudAusenciaModel.fecha_inicio <= payload.fecha_fin,
            SolicitudAusenciaModel.fecha_fin >= payload.fecha_inicio,
        )
    )
    if overlapping:
        raise HTTPException(409, "Ya existe una ausencia en estas fechas")
    row = SolicitudAusenciaModel(
        empresa_id=user.empresa_id,
        empleado_id=worker.id,
        tipo_ausencia_id=kind.id,
        fecha_inicio=payload.fecha_inicio,
        fecha_fin=payload.fecha_fin,
        dias_solicitados=days,
        motivo=payload.motivo,
        documento_url=f"documento:{payload.documento_id}" if payload.documento_id else None,
    )
    session.add(row)
    await session.flush()
    return {"id": row.id, "estado": row.estado, "dias_solicitados": days}


@router.get("/mi/ausencias", summary="Consultar mis solicitudes")
async def my_absences(
    user: CurrentUser = Depends(require_scoped_permission("ausencias:mi", "platform:ausencias:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    rows = (
        await session.scalars(
            select(SolicitudAusenciaModel)
            .where(
                SolicitudAusenciaModel.empresa_id == user.empresa_id,
                SolicitudAusenciaModel.empleado_id == worker.id,
            )
            .order_by(SolicitudAusenciaModel.creado_en.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "tipo_ausencia_id": r.tipo_ausencia_id,
            "fecha_inicio": r.fecha_inicio,
            "fecha_fin": r.fecha_fin,
            "dias_solicitados": r.dias_solicitados,
            "dias_descontados": r.dias_descontados,
            "estado": r.estado,
            "observacion_jefe": r.observacion_jefe,
        }
        for r in rows
    ]


@router.get("/ausencias", summary="Consultar solicitudes de la empresa")
async def company_absences(
    empresa_id: UUID | None = None,
    estado: str | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("ausencias:gestionar", "platform:ausencias:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    query = select(SolicitudAusenciaModel).where(SolicitudAusenciaModel.empresa_id == company)
    if estado:
        query = query.where(SolicitudAusenciaModel.estado == estado)
    rows = (
        await session.scalars(query.order_by(SolicitudAusenciaModel.creado_en.desc()).limit(100))
    ).all()
    return [
        {
            "id": r.id,
            "empleado_id": r.empleado_id,
            "tipo_ausencia_id": r.tipo_ausencia_id,
            "fecha_inicio": r.fecha_inicio,
            "fecha_fin": r.fecha_fin,
            "estado": r.estado,
        }
        for r in rows
    ]


@router.get("/mi/equipo/ausencias", summary="Consultar solicitudes de mi equipo")
async def team_absences(
    user: CurrentUser = Depends(
        require_scoped_permission("ausencias:aprobar", "platform:ausencias:aprobar")
    ),
    session: AsyncSession = Depends(get_session),
):
    leader = await self_employee(session, user)
    team = select(ContratoModel.empleado_id).where(
        ContratoModel.empresa_id == user.empresa_id,
        ContratoModel.jefe_directo_id == leader.id,
        ContratoModel.estado == "VIGENTE",
    )
    rows = (
        await session.scalars(
            select(SolicitudAusenciaModel)
            .where(
                SolicitudAusenciaModel.empresa_id == user.empresa_id,
                SolicitudAusenciaModel.empleado_id.in_(team),
            )
            .order_by(SolicitudAusenciaModel.creado_en.desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "id": r.id,
            "empleado_id": r.empleado_id,
            "fecha_inicio": r.fecha_inicio,
            "fecha_fin": r.fecha_fin,
            "estado": r.estado,
        }
        for r in rows
    ]


@router.post("/ausencias/{solicitud_id}/decision", summary="Aprobar o rechazar ausencia")
async def decide_absence(
    solicitud_id: UUID,
    payload: AbsenceDecision,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("ausencias:aprobar", "platform:ausencias:aprobar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    row = await session.scalar(
        select(SolicitudAusenciaModel)
        .where(
            SolicitudAusenciaModel.id == str(solicitud_id),
            SolicitudAusenciaModel.empresa_id == company,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Solicitud no encontrada")
    if row.estado != "PENDIENTE":
        raise HTTPException(409, "Solicitud ya resuelta")
    target = await employee(session, company, row.empleado_id)
    if target.usuario_id == user.id:
        raise HTTPException(403, "No puedes aprobar tu propia ausencia")
    if "JEFE_AREA" in user.roles and "RRHH" not in user.roles and "ADMIN_EMPRESA" not in user.roles:
        leader = await session.scalar(
            select(EmpleadoModel.id).where(
                EmpleadoModel.empresa_id == company, EmpleadoModel.usuario_id == user.id
            )
        )
        manages = (
            await session.scalar(
                select(ContratoModel.id).where(
                    ContratoModel.empresa_id == company,
                    ContratoModel.empleado_id == target.id,
                    ContratoModel.jefe_directo_id == leader,
                    ContratoModel.estado == "VIGENTE",
                )
            )
            if leader
            else None
        )
        if not manages:
            raise HTTPException(403, "No perteneces a la jefatura de este empleado")
    kind = await session.scalar(
        select(TipoAusenciaModel).where(
            TipoAusenciaModel.id == row.tipo_ausencia_id, TipoAusenciaModel.empresa_id == company
        )
    )
    if payload.aprobar and kind.descuenta_vacacion:
        if row.fecha_inicio.year != row.fecha_fin.year:
            raise HTTPException(422, "Una vacacion no puede cruzar gestiones en una solicitud")
        if (
            payload.dias_habiles_vacacion is None
            or payload.dias_habiles_vacacion > row.dias_solicitados
        ):
            raise HTTPException(422, "Indica los dias habiles de vacacion verificados")
        balance = await session.scalar(
            select(SaldoVacacionModel)
            .where(
                SaldoVacacionModel.empresa_id == company,
                SaldoVacacionModel.empleado_id == target.id,
                SaldoVacacionModel.gestion == row.fecha_inicio.year,
            )
            .with_for_update()
        )
        if (
            balance is None
            or balance.dias_asignados - balance.dias_usados < payload.dias_habiles_vacacion
        ):
            raise HTTPException(409, "Saldo de vacaciones insuficiente")
        balance.dias_usados += payload.dias_habiles_vacacion
        row.dias_descontados = payload.dias_habiles_vacacion
    row.estado = "APROBADA" if payload.aprobar else "RECHAZADA"
    row.observacion_jefe = payload.observacion
    row.resuelto_por_id = user.id
    row.resuelto_en = datetime.now(UTC)
    await record_personal_event(
        session,
        user,
        company,
        action="AUSENCIA_RESUELTA",
        table="solicitud_ausencia",
        record_id=row.id,
        data={"estado": row.estado, "dias_descontados": row.dias_descontados},
    )
    return {"id": row.id, "estado": row.estado, "dias_descontados": row.dias_descontados}
