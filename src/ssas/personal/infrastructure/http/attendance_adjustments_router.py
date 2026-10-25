"""Audited attendance corrections and two-step overtime authorization."""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import get_session
from ssas.personal.application.attendance import minutes_late, worked_hours
from ssas.personal.application.audit import record_personal_event
from ssas.personal.application.payroll import PayrollConfigurationError, calculate_ordinary_overtime
from ssas.personal.infrastructure.http.router import self_employee, tenant
from ssas.personal.infrastructure.persistence.models import (
    AsistenciaModel,
    AutorizacionHorasExtraModel,
    ContratoModel,
    PeriodoNominaModel,
    SolicitudCorreccionAsistenciaModel,
)

router = APIRouter(prefix="/personal", tags=["Personal"])
LOCAL_ZONE = ZoneInfo("America/La_Paz")


class CorrectionInput(BaseModel):
    fecha: date
    asistencia_id: UUID | None = None
    nueva_entrada: AwareDatetime
    nueva_salida: AwareDatetime
    motivo: str = Field(min_length=3, max_length=2000)


class OvertimeInput(BaseModel):
    asistencia_id: UUID
    horas_solicitadas: Decimal = Field(gt=0, decimal_places=2)
    motivo: str = Field(min_length=3, max_length=2000)


class BossDecision(BaseModel):
    aprobar: bool
    observacion: str = Field(min_length=3, max_length=2000)


class HRDecision(BossDecision):
    monto_autorizado: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    referencia_calculo: str | None = Field(default=None, min_length=3, max_length=160)
    calculo_automatico: bool = False
    dia_no_feriado_confirmado: bool = False


async def _editable_period(session: AsyncSession, company: str, day: date) -> None:
    state = await session.scalar(
        select(PeriodoNominaModel.estado)
        .where(
            PeriodoNominaModel.empresa_id == company,
            PeriodoNominaModel.gestion == day.year,
            PeriodoNominaModel.mes == day.month,
        )
        .with_for_update()
    )
    if state is not None and state != "ABIERTO":
        raise HTTPException(409, "El periodo de nomina ya fue calculado o aprobado")


async def _attendance(
    session: AsyncSession, company: str, attendance_id: str, *, lock: bool = False
) -> AsistenciaModel:
    query = select(AsistenciaModel).where(
        AsistenciaModel.id == attendance_id, AsistenciaModel.empresa_id == company
    )
    row = await session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Asistencia no encontrada")
    return row


async def _current_boss(
    session: AsyncSession, user: CurrentUser, company: str, target_id: str
) -> None:
    if not user.empresa_id:
        raise HTTPException(403, "La decision corresponde al jefe directo de la empresa")
    boss = await self_employee(session, user)
    if boss.id == target_id:
        raise HTTPException(403, "No puedes aprobar tu propia asistencia")
    today = datetime.now(UTC).astimezone(LOCAL_ZONE).date()
    manages = await session.scalar(
        select(ContratoModel.id).where(
            ContratoModel.empresa_id == company,
            ContratoModel.empleado_id == target_id,
            ContratoModel.jefe_directo_id == boss.id,
            ContratoModel.fecha_inicio <= today,
            (ContratoModel.fecha_fin.is_(None) | (ContratoModel.fecha_fin >= today)),
            ContratoModel.estado == "VIGENTE",
        )
    )
    if manages is None:
        raise HTTPException(403, "No eres el jefe directo vigente de este empleado")


@router.post(
    "/mi/asistencia/correcciones", status_code=201, summary="Solicitar correccion de fichaje"
)
async def request_correction(
    payload: CorrectionInput,
    user: CurrentUser = Depends(
        require_scoped_permission(
            "asistencia:solicitar_ajuste", "platform:asistencia:solicitar_ajuste"
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    if payload.fecha > datetime.now(UTC).astimezone(LOCAL_ZONE).date():
        raise HTTPException(422, "No se puede corregir un dia futuro")
    row = None
    if payload.asistencia_id is not None:
        row = await _attendance(session, user.empresa_id, str(payload.asistencia_id), lock=True)
        if row.empleado_id != worker.id or row.fecha != payload.fecha:
            raise HTTPException(403, "No es tu asistencia de esa fecha")
    elif await session.scalar(
        select(AsistenciaModel.id).where(
            AsistenciaModel.empresa_id == user.empresa_id,
            AsistenciaModel.empleado_id == worker.id,
            AsistenciaModel.fecha == payload.fecha,
        )
    ):
        raise HTTPException(409, "Ya existe un fichaje; indica asistencia_id para corregirlo")
    await _editable_period(session, user.empresa_id, payload.fecha)
    if payload.nueva_entrada.astimezone(LOCAL_ZONE).date() != payload.fecha:
        raise HTTPException(422, "La nueva entrada debe corresponder al dia fichado")
    if payload.nueva_salida <= payload.nueva_entrada:
        raise HTTPException(422, "La salida debe ser posterior a la entrada")
    if await session.scalar(
        select(SolicitudCorreccionAsistenciaModel.id).where(
            SolicitudCorreccionAsistenciaModel.empresa_id == user.empresa_id,
            SolicitudCorreccionAsistenciaModel.empleado_id == worker.id,
            SolicitudCorreccionAsistenciaModel.fecha == payload.fecha,
            SolicitudCorreccionAsistenciaModel.estado == "PENDIENTE",
        )
    ):
        raise HTTPException(409, "Ya hay una correccion pendiente")
    if row is not None and await session.scalar(
        select(AutorizacionHorasExtraModel.id).where(
            AutorizacionHorasExtraModel.asistencia_id == row.id
        )
    ):
        raise HTTPException(409, "Resuelve la autorizacion de horas extra antes de corregir")
    request = SolicitudCorreccionAsistenciaModel(
        empresa_id=user.empresa_id,
        empleado_id=worker.id,
        asistencia_id=row.id if row else None,
        fecha=payload.fecha,
        nueva_entrada=payload.nueva_entrada,
        nueva_salida=payload.nueva_salida,
        motivo=payload.motivo,
        estado="PENDIENTE",
    )
    session.add(request)
    await session.flush()
    await record_personal_event(
        session,
        user,
        user.empresa_id,
        action="CORRECCION_SOLICITADA",
        table="solicitud_correccion_asistencia",
        record_id=request.id,
    )
    return {"id": request.id, "estado": request.estado}


@router.post(
    "/asistencia/correcciones/{solicitud_id}/decision",
    summary="Resolver correccion como jefe directo",
)
async def decide_correction(
    solicitud_id: UUID,
    payload: BossDecision,
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:aprobar_ajuste", "platform:asistencia:aprobar_ajuste")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, None)
    request = await session.scalar(
        select(SolicitudCorreccionAsistenciaModel)
        .where(
            SolicitudCorreccionAsistenciaModel.id == str(solicitud_id),
            SolicitudCorreccionAsistenciaModel.empresa_id == company,
        )
        .with_for_update()
    )
    if request is None:
        raise HTTPException(404, "Solicitud no encontrada")
    if request.estado != "PENDIENTE":
        raise HTTPException(409, "Solicitud ya resuelta")
    await _current_boss(session, user, company, request.empleado_id)
    await _editable_period(session, company, request.fecha)
    row = (
        await _attendance(session, company, request.asistencia_id, lock=True)
        if request.asistencia_id
        else None
    )
    if row is not None and (row.empleado_id != request.empleado_id or row.fecha != request.fecha):
        raise HTTPException(409, "El fichaje no coincide con la solicitud")
    if payload.aprobar:
        contract = await session.scalar(
            select(ContratoModel)
            .where(
                ContratoModel.empresa_id == company,
                ContratoModel.empleado_id == request.empleado_id,
                ContratoModel.fecha_inicio <= request.fecha,
                (ContratoModel.fecha_fin.is_(None) | (ContratoModel.fecha_fin >= request.fecha)),
            )
            .order_by(ContratoModel.fecha_inicio.desc())
        )
        if contract is None:
            raise HTTPException(409, "No hay contrato para el fichaje")
        try:
            worked, overtime = worked_hours(
                request.nueva_entrada,
                request.nueva_salida,
                contract.minutos_descanso,
                contract.horas_jornada,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if row is None:
            existing = await session.scalar(
                select(AsistenciaModel.id).where(
                    AsistenciaModel.empresa_id == company,
                    AsistenciaModel.empleado_id == request.empleado_id,
                    AsistenciaModel.fecha == request.fecha,
                )
            )
            if existing:
                raise HTTPException(409, "Ya se registro un fichaje para esa fecha")
            row = AsistenciaModel(
                empresa_id=company,
                empleado_id=request.empleado_id,
                fecha=request.fecha,
                hora_entrada=request.nueva_entrada,
                hora_salida=request.nueva_salida,
                origen="MANUAL",
            )
            session.add(row)
            await session.flush()
            request.asistencia_id = row.id
            old = None
        else:
            old = {
                "entrada": row.hora_entrada.isoformat(),
                "salida": row.hora_salida.isoformat() if row.hora_salida else None,
            }
        row.hora_entrada = request.nueva_entrada
        row.hora_salida = request.nueva_salida
        row.horas_trabajadas = worked
        row.horas_extra = overtime
        row.minutos_retraso = minutes_late(
            request.nueva_entrada.astimezone(LOCAL_ZONE), contract.hora_entrada_programada
        )
        row.lat_entrada = row.lon_entrada = row.lat_salida = row.lon_salida = None
        row.origen = "MANUAL"
        await record_personal_event(
            session,
            user,
            company,
            action="ASISTENCIA_CORREGIDA",
            table="asistencia",
            record_id=row.id,
            data={
                "anterior": old,
                "entrada": row.hora_entrada.isoformat(),
                "salida": row.hora_salida.isoformat(),
            },
        )
    request.estado = "APROBADA" if payload.aprobar else "RECHAZADA"
    request.observacion_jefe = payload.observacion
    request.resuelto_por_id = user.id
    request.resuelto_en = datetime.now(UTC)
    await record_personal_event(
        session,
        user,
        company,
        action="CORRECCION_RESUELTA",
        table="solicitud_correccion_asistencia",
        record_id=request.id,
        data={"estado": request.estado},
    )
    return {"id": request.id, "estado": request.estado}


@router.post(
    "/mi/asistencia/horas-extra", status_code=201, summary="Solicitar horas extra fichadas"
)
async def request_overtime(
    payload: OvertimeInput,
    user: CurrentUser = Depends(
        require_scoped_permission(
            "asistencia:solicitar_ajuste", "platform:asistencia:solicitar_ajuste"
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    row = await _attendance(session, user.empresa_id, str(payload.asistencia_id), lock=True)
    if row.empleado_id != worker.id:
        raise HTTPException(403, "No es tu asistencia")
    await _editable_period(session, user.empresa_id, row.fecha)
    if row.hora_salida is None or payload.horas_solicitadas > row.horas_extra:
        raise HTTPException(422, "Las horas solicitadas superan las fichadas")
    if await session.scalar(
        select(AutorizacionHorasExtraModel.id).where(
            AutorizacionHorasExtraModel.asistencia_id == row.id
        )
    ):
        raise HTTPException(409, "Las horas extra ya tienen solicitud")
    if await session.scalar(
        select(SolicitudCorreccionAsistenciaModel.id).where(
            SolicitudCorreccionAsistenciaModel.asistencia_id == row.id,
            SolicitudCorreccionAsistenciaModel.estado == "PENDIENTE",
        )
    ):
        raise HTTPException(409, "Primero debe resolverse la correccion pendiente")
    request = AutorizacionHorasExtraModel(
        empresa_id=user.empresa_id,
        empleado_id=worker.id,
        asistencia_id=row.id,
        horas_solicitadas=payload.horas_solicitadas,
        motivo=payload.motivo,
        estado="JEFE_PENDIENTE",
    )
    session.add(request)
    await session.flush()
    await record_personal_event(
        session,
        user,
        user.empresa_id,
        action="HORAS_EXTRA_SOLICITADAS",
        table="autorizacion_horas_extra",
        record_id=request.id,
    )
    return {"id": request.id, "estado": request.estado}


@router.post(
    "/asistencia/horas-extra/{solicitud_id}/jefe", summary="Confirmar horas extra como jefe directo"
)
async def decide_overtime_boss(
    solicitud_id: UUID,
    payload: BossDecision,
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:aprobar_ajuste", "platform:asistencia:aprobar_ajuste")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, None)
    request = await session.scalar(
        select(AutorizacionHorasExtraModel)
        .where(
            AutorizacionHorasExtraModel.id == str(solicitud_id),
            AutorizacionHorasExtraModel.empresa_id == company,
        )
        .with_for_update()
    )
    if request is None:
        raise HTTPException(404, "Solicitud no encontrada")
    if request.estado != "JEFE_PENDIENTE":
        raise HTTPException(409, "La solicitud ya fue revisada por el jefe")
    await _current_boss(session, user, company, request.empleado_id)
    row = await _attendance(session, company, request.asistencia_id, lock=True)
    await _editable_period(session, company, row.fecha)
    request.estado = "RRHH_PENDIENTE" if payload.aprobar else "RECHAZADO"
    request.jefe_id = user.id
    request.jefe_en = datetime.now(UTC)
    request.observacion = payload.observacion
    await record_personal_event(
        session,
        user,
        company,
        action="HORAS_EXTRA_JEFE_RESUELTAS",
        table="autorizacion_horas_extra",
        record_id=request.id,
        data={"estado": request.estado},
    )
    return {"id": request.id, "estado": request.estado}


@router.post(
    "/asistencia/horas-extra/{solicitud_id}/rrhh", summary="Autorizar horas extra para nomina"
)
async def decide_overtime_hr(
    solicitud_id: UUID,
    payload: HRDecision,
    user: CurrentUser = Depends(
        require_scoped_permission(
            "asistencia:autorizar_extra", "platform:asistencia:autorizar_extra"
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, None)
    request = await session.scalar(
        select(AutorizacionHorasExtraModel)
        .where(
            AutorizacionHorasExtraModel.id == str(solicitud_id),
            AutorizacionHorasExtraModel.empresa_id == company,
        )
        .with_for_update()
    )
    if request is None:
        raise HTTPException(404, "Solicitud no encontrada")
    if request.estado != "RRHH_PENDIENTE":
        raise HTTPException(409, "Primero debe confirmar el jefe directo")
    if request.jefe_id == user.id:
        raise HTTPException(403, "La autorizacion final requiere otra persona")
    own_employee = await session.scalar(
        select(EmpleadoModel.id).where(
            EmpleadoModel.empresa_id == company,
            EmpleadoModel.usuario_id == user.id,
        )
    )
    if own_employee == request.empleado_id:
        raise HTTPException(403, "No puedes autorizar tus propias horas extra")
    row = await _attendance(session, company, request.asistencia_id, lock=True)
    await _editable_period(session, company, row.fecha)
    if payload.aprobar and payload.calculo_automatico:
        if payload.monto_autorizado is not None or payload.referencia_calculo is not None:
            raise HTTPException(422, "El calculo automatico no admite un importe manual")
        if not payload.dia_no_feriado_confirmado or row.fecha.weekday() == 6:
            raise HTTPException(409, "Dia no confirmado como ordinario; requiere revision")
        if (
            row.hora_salida is None
            or request.horas_solicitadas > row.horas_extra
            or row.horas_extra <= 0
        ):
            raise HTTPException(409, "Las horas autorizadas no coinciden con el fichaje")
        end = row.hora_salida.astimezone(LOCAL_ZONE)
        start = end - timedelta(seconds=int(request.horas_solicitadas * Decimal(3600)))
        if (
            start.date() != row.fecha
            or end.date() != row.fecha
            or start.time() < time(6)
            or end.time() > time(20)
        ):
            raise HTTPException(409, "Horario nocturno o entre dias; requiere revision")
        contracts = (
            await session.scalars(
                select(ContratoModel).where(
                    ContratoModel.empresa_id == company,
                    ContratoModel.empleado_id == request.empleado_id,
                    ContratoModel.fecha_inicio <= row.fecha,
                    (ContratoModel.fecha_fin.is_(None) | (ContratoModel.fecha_fin >= row.fecha)),
                )
            )
        ).all()
        if len(contracts) != 1:
            raise HTTPException(409, "Se requiere un contrato unico para calcular horas extra")
        try:
            payload_amount = calculate_ordinary_overtime(
                contracts[0].salario_basico,
                contracts[0].horas_jornada,
                request.horas_solicitadas,
            )
        except PayrollConfigurationError as exc:
            raise HTTPException(409, str(exc)) from exc
        request.monto_autorizado = payload_amount
        request.referencia_calculo = "AUTO_DIURNA_30D_100PCT"
    elif payload.aprobar and (
        payload.monto_autorizado is None or payload.referencia_calculo is None
    ):
        raise HTTPException(422, "Indica monto y referencia de calculo verificados")
    request.estado = "AUTORIZADO" if payload.aprobar else "RECHAZADO"
    request.rrhh_id = user.id
    request.rrhh_en = datetime.now(UTC)
    request.observacion = payload.observacion
    if payload.aprobar and not payload.calculo_automatico:
        request.monto_autorizado = payload.monto_autorizado
        request.referencia_calculo = payload.referencia_calculo
    await record_personal_event(
        session,
        user,
        company,
        action="HORAS_EXTRA_RRHH_RESUELTAS",
        table="autorizacion_horas_extra",
        record_id=request.id,
        data={
            "estado": request.estado,
            "monto_autorizado": str(request.monto_autorizado) if request.monto_autorizado else None,
            "calculo_automatico": payload.calculo_automatico,
            "dia_no_feriado_confirmado": payload.dia_no_feriado_confirmado,
        },
    )
    return {
        "id": request.id,
        "estado": request.estado,
        "monto_autorizado": request.monto_autorizado,
        "referencia_calculo": request.referencia_calculo,
    }


@router.get("/mi/asistencia/ajustes", summary="Consultar mis ajustes de asistencia")
async def my_adjustments(
    user: CurrentUser = Depends(
        require_scoped_permission(
            "asistencia:solicitar_ajuste", "platform:asistencia:solicitar_ajuste"
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    corrections = (
        await session.scalars(
            select(SolicitudCorreccionAsistenciaModel)
            .where(
                SolicitudCorreccionAsistenciaModel.empresa_id == user.empresa_id,
                SolicitudCorreccionAsistenciaModel.empleado_id == worker.id,
            )
            .order_by(SolicitudCorreccionAsistenciaModel.creado_en.desc())
            .limit(100)
        )
    ).all()
    overtime = (
        await session.scalars(
            select(AutorizacionHorasExtraModel)
            .where(
                AutorizacionHorasExtraModel.empresa_id == user.empresa_id,
                AutorizacionHorasExtraModel.empleado_id == worker.id,
            )
            .order_by(AutorizacionHorasExtraModel.creado_en.desc())
            .limit(100)
        )
    ).all()
    return {
        "correcciones": [
            {
                "id": row.id,
                "fecha": row.fecha,
                "asistencia_id": row.asistencia_id,
                "estado": row.estado,
            }
            for row in corrections
        ],
        "horas_extra": [
            {
                "id": row.id,
                "asistencia_id": row.asistencia_id,
                "estado": row.estado,
                "horas": row.horas_solicitadas,
            }
            for row in overtime
        ],
    }


@router.get("/mi/equipo/asistencia/ajustes", summary="Consultar ajustes pendientes de mi equipo")
async def team_adjustments(
    user: CurrentUser = Depends(
        require_scoped_permission("asistencia:aprobar_ajuste", "platform:asistencia:aprobar_ajuste")
    ),
    session: AsyncSession = Depends(get_session),
):
    boss = await self_employee(session, user)
    today = datetime.now(UTC).astimezone(LOCAL_ZONE).date()
    team = select(ContratoModel.empleado_id).where(
        ContratoModel.empresa_id == user.empresa_id,
        ContratoModel.jefe_directo_id == boss.id,
        ContratoModel.fecha_inicio <= today,
        (ContratoModel.fecha_fin.is_(None) | (ContratoModel.fecha_fin >= today)),
        ContratoModel.estado == "VIGENTE",
    )
    corrections = (
        await session.scalars(
            select(SolicitudCorreccionAsistenciaModel)
            .where(
                SolicitudCorreccionAsistenciaModel.empresa_id == user.empresa_id,
                SolicitudCorreccionAsistenciaModel.empleado_id.in_(team),
                SolicitudCorreccionAsistenciaModel.estado == "PENDIENTE",
            )
            .limit(100)
        )
    ).all()
    overtime = (
        await session.scalars(
            select(AutorizacionHorasExtraModel)
            .where(
                AutorizacionHorasExtraModel.empresa_id == user.empresa_id,
                AutorizacionHorasExtraModel.empleado_id.in_(team),
                AutorizacionHorasExtraModel.estado == "JEFE_PENDIENTE",
            )
            .limit(100)
        )
    ).all()
    return {
        "correcciones": [
            {"id": row.id, "empleado_id": row.empleado_id, "asistencia_id": row.asistencia_id}
            for row in corrections
        ],
        "horas_extra": [
            {
                "id": row.id,
                "empleado_id": row.empleado_id,
                "asistencia_id": row.asistencia_id,
                "horas": row.horas_solicitadas,
            }
            for row in overtime
        ],
    }


@router.get(
    "/asistencia/horas-extra/pendientes-rrhh", summary="Consultar horas extra pendientes de RRHH"
)
async def pending_hr_overtime(
    user: CurrentUser = Depends(
        require_scoped_permission(
            "asistencia:autorizar_extra", "platform:asistencia:autorizar_extra"
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, None)
    rows = (
        await session.scalars(
            select(AutorizacionHorasExtraModel)
            .where(
                AutorizacionHorasExtraModel.empresa_id == company,
                AutorizacionHorasExtraModel.estado == "RRHH_PENDIENTE",
            )
            .order_by(AutorizacionHorasExtraModel.creado_en)
            .limit(100)
        )
    ).all()
    return [
        {
            "id": row.id,
            "empleado_id": row.empleado_id,
            "horas": row.horas_solicitadas,
            "jefe_id": row.jefe_id,
        }
        for row in rows
    ]
