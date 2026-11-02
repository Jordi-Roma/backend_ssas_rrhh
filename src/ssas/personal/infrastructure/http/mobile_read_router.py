"""Lecturas de autoservicio móvil que no exponen datos de otra empresa."""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.cargos.infrastructure.persistence.models.cargo import CargoModel
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import get_session
from ssas.personal.infrastructure.http.router import self_employee
from ssas.personal.infrastructure.persistence.models import (
    AsistenciaModel,
    ContratoModel,
    SaldoVacacionModel,
    SolicitudAusenciaModel,
    TipoAusenciaModel,
)

router = APIRouter(prefix="/personal/mi", tags=["Personal"])


@router.get("/vacaciones", summary="Consultar mi saldo de vacaciones")
async def my_vacation_balances(
    user: CurrentUser = Depends(require_scoped_permission("ausencias:mi", "platform:ausencias:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    rows = (await session.scalars(select(SaldoVacacionModel).where(
        SaldoVacacionModel.empresa_id == user.empresa_id,
        SaldoVacacionModel.empleado_id == worker.id,
    ).order_by(SaldoVacacionModel.gestion.desc()))).all()
    return [
        {
            "id": row.id,
            "empleado_id": row.empleado_id,
            "gestion": row.gestion,
            "dias_asignados": row.dias_asignados,
            "dias_usados": row.dias_usados,
            "dias_saldo": row.dias_asignados - row.dias_usados,
        }
        for row in rows
    ]


@router.get("/equipo/resumen", summary="Consultar mi equipo y su asistencia de hoy")
async def my_team_summary(
    user: CurrentUser = Depends(require_scoped_permission("asistencia:ver_equipo", "platform:asistencia:ver_equipo")),
    session: AsyncSession = Depends(get_session),
):
    leader = await self_employee(session, user)
    today = datetime.now(ZoneInfo("America/La_Paz")).date()
    rows = (await session.execute(
        select(ContratoModel, EmpleadoModel, CargoModel)
        .join(EmpleadoModel, EmpleadoModel.id == ContratoModel.empleado_id)
        .join(CargoModel, CargoModel.id == ContratoModel.cargo_id)
        .where(
            ContratoModel.empresa_id == user.empresa_id,
            EmpleadoModel.empresa_id == user.empresa_id,
            CargoModel.empresa_id == user.empresa_id,
            ContratoModel.jefe_directo_id == leader.id,
            ContratoModel.estado == "VIGENTE",
            ContratoModel.fecha_inicio <= today,
            or_(ContratoModel.fecha_fin.is_(None), ContratoModel.fecha_fin >= today),
        )
        .order_by(EmpleadoModel.nombres, EmpleadoModel.apellido_paterno)
    )).all()
    attendance = (await session.scalars(select(AsistenciaModel).where(
        AsistenciaModel.empresa_id == user.empresa_id,
        AsistenciaModel.fecha == today,
        AsistenciaModel.empleado_id.in_([employee.id for _, employee, _ in rows]),
    ))).all() if rows else []
    by_employee = {item.empleado_id: item for item in attendance}
    return [
        {
            "contrato": {
                "id": contract.id,
                "empleado_id": employee.id,
                "cargo_id": cargo.id,
                "numero_contrato": contract.numero_contrato,
                "estado": contract.estado,
            },
            "empleado": {
                "id": employee.id,
                "codigo": employee.codigo,
                "nombres": employee.nombres,
                "apellido_paterno": employee.apellido_paterno,
                "apellido_materno": employee.apellido_materno,
            },
            "cargo": {"id": cargo.id, "nombre": cargo.nombre},
            "asistencia": (
                {
                    "id": by_employee[employee.id].id,
                    "empleado_id": employee.id,
                    "fecha": by_employee[employee.id].fecha,
                    "hora_entrada": by_employee[employee.id].hora_entrada,
                    "hora_salida": by_employee[employee.id].hora_salida,
                    "horas_trabajadas": by_employee[employee.id].horas_trabajadas,
                }
                if employee.id in by_employee else None
            ),
        }
        for contract, employee, cargo in rows
    ]


@router.get("/equipo/ausencias/resumen", summary="Consultar solicitudes para mi aprobación")
async def my_team_absence_summary(
    user: CurrentUser = Depends(require_scoped_permission("ausencias:aprobar", "platform:ausencias:aprobar")),
    session: AsyncSession = Depends(get_session),
):
    if not user.empresa_id:
        return []
    query = (
        select(SolicitudAusenciaModel, EmpleadoModel, TipoAusenciaModel)
        .join(EmpleadoModel, EmpleadoModel.id == SolicitudAusenciaModel.empleado_id)
        .join(TipoAusenciaModel, TipoAusenciaModel.id == SolicitudAusenciaModel.tipo_ausencia_id)
        .where(
            SolicitudAusenciaModel.empresa_id == user.empresa_id,
            EmpleadoModel.empresa_id == user.empresa_id,
            TipoAusenciaModel.empresa_id == user.empresa_id,
            or_(EmpleadoModel.usuario_id.is_(None), EmpleadoModel.usuario_id != user.id),
        )
    )
    if "RRHH" not in user.roles and "ADMIN_EMPRESA" not in user.roles:
        leader = await self_employee(session, user)
        team_ids = select(ContratoModel.empleado_id).where(
            ContratoModel.empresa_id == user.empresa_id,
            ContratoModel.jefe_directo_id == leader.id,
            ContratoModel.estado == "VIGENTE",
            ContratoModel.fecha_inicio <= datetime.now(ZoneInfo("America/La_Paz")).date(),
            or_(ContratoModel.fecha_fin.is_(None),
                ContratoModel.fecha_fin >= datetime.now(ZoneInfo("America/La_Paz")).date()),
        )
        query = query.where(SolicitudAusenciaModel.empleado_id.in_(team_ids))
    rows = (await session.execute(
        query.order_by(SolicitudAusenciaModel.creado_en.desc()).limit(100)
    )).all()
    ids = [worker.id for _, worker, _ in rows]
    balances = (await session.scalars(select(SaldoVacacionModel).where(
        SaldoVacacionModel.empresa_id == user.empresa_id,
        SaldoVacacionModel.empleado_id.in_(ids),
    ))).all() if ids else []
    balance_by_employee_year = {(b.empleado_id, b.gestion): b for b in balances}
    return [
        {
            "id": request.id,
            "empleado_id": worker.id,
            "tipo_ausencia_id": kind.id,
            "fecha_inicio": request.fecha_inicio,
            "fecha_fin": request.fecha_fin,
            "dias_solicitados": request.dias_solicitados,
            "motivo": request.motivo,
            "documento_url": "documento:adjunto" if request.documento_url else None,
            "estado": request.estado,
            "observacion_jefe": request.observacion_jefe,
            "creado_en": request.creado_en,
            "resuelto_en": request.resuelto_en,
            "empleado": {
                "id": worker.id,
                "nombres": worker.nombres,
                "apellido_paterno": worker.apellido_paterno,
                "apellido_materno": worker.apellido_materno,
            },
            "tipo": {
                "id": kind.id,
                "codigo": kind.codigo,
                "nombre": kind.nombre,
                "es_remunerado": kind.es_remunerado,
                "descuenta_vacacion": kind.descuenta_vacacion,
                "requiere_documento": kind.requiere_documento,
            },
            "saldo": (
                {
                    "id": balance_by_employee_year[(worker.id, request.fecha_inicio.year)].id,
                    "empleado_id": worker.id,
                    "gestion": request.fecha_inicio.year,
                    "dias_asignados": balance_by_employee_year[(worker.id, request.fecha_inicio.year)].dias_asignados,
                    "dias_usados": balance_by_employee_year[(worker.id, request.fecha_inicio.year)].dias_usados,
                    "dias_saldo": balance_by_employee_year[(worker.id, request.fecha_inicio.year)].dias_asignados
                    - balance_by_employee_year[(worker.id, request.fecha_inicio.year)].dias_usados,
                }
                if (worker.id, request.fecha_inicio.year) in balance_by_employee_year else None
            ),
        }
        for request, worker, kind in rows
    ]
