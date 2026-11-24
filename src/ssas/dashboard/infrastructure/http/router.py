"""Resumen agregado para la pantalla de inicio, por alcance de la identidad.

Todo se resuelve con ``func.count`` y agrupaciones: la única consulta que trae filas
completas es la de las cinco últimas entradas de bitácora.
"""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.bitacora.infrastructure.persistence.models.audit_log import AuditLogModel
from ssas.cargos.infrastructure.persistence.models.cargo import CargoModel
from ssas.core.api.openapi import TAG_DASHBOARD
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.departamentos.infrastructure.persistence.models.departamento import DepartamentoModel
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.session import get_session
from ssas.postulaciones.infrastructure.persistence.models.etapa_reclutamiento import (
    EtapaReclutamientoModel,
)
from ssas.postulaciones.infrastructure.persistence.models.postulacion import PostulacionModel
from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel

router = APIRouter(prefix="/dashboard", tags=[TAG_DASHBOARD])


class BitacoraResumen(BaseModel):
    id: str
    modulo: str
    accion: str
    nivel: str
    descripcion: str
    actor: str | None
    fecha: datetime


class ResumenEmpresa(BaseModel):
    usuarios_activos: int
    usuarios_inactivos: int
    vacantes_por_estado: dict[str, int]
    postulaciones_por_etapa: dict[str, int]
    departamentos: int
    cargos: int


class ResumenPlataforma(BaseModel):
    empresas_activas: int
    empresas_suspendidas: int
    empresas_eliminadas: int
    usuarios_totales: int
    vacantes_publicadas: int
    postulaciones_del_mes: int


class ResumenDashboardResponse(BaseModel):
    alcance: Literal["EMPRESA", "PLATAFORMA"]
    empresa_id: str | None = None
    empresa: ResumenEmpresa | None = None
    plataforma: ResumenPlataforma | None = None
    bitacora_reciente: list[BitacoraResumen] = Field(default_factory=list)


async def _bitacora_reciente(
    session: AsyncSession, empresa_id: str | None
) -> list[BitacoraResumen]:
    """Últimos eventos de la empresa o, para plataforma, de todas las empresas."""
    query = (
        select(AuditLogModel, UserModel.name, UserModel.apellido)
        .outerjoin(UserModel, UserModel.id == AuditLogModel.user_id)
        .order_by(AuditLogModel.fecha.desc())
        .limit(8)
    )
    if empresa_id is not None:
        query = query.where(AuditLogModel.empresa_id == empresa_id)
    result = await session.execute(query)
    return [
        BitacoraResumen(
            id=registro.id,
            modulo=registro.module,
            accion=registro.action,
            nivel=registro.level,
            descripcion=registro.description,
            actor=registro.actor_label or (f"{nombre} {apellido}".strip() if nombre else None),
            fecha=registro.fecha,
        )
        for registro, nombre, apellido in result.all()
    ]


async def _resumen_empresa(session: AsyncSession, empresa_id: str) -> ResumenEmpresa:
    usuarios = await session.execute(
        select(UserModel.is_active, func.count())
        .where(UserModel.empresa_id == empresa_id, UserModel.eliminado_at.is_(None))
        .group_by(UserModel.is_active)
    )
    conteo_usuarios = {activo: total for activo, total in usuarios.all()}

    vacantes = await session.execute(
        select(VacanteModel.estado, func.count())
        .where(VacanteModel.empresa_id == empresa_id)
        .group_by(VacanteModel.estado)
    )
    postulaciones = await session.execute(
        select(EtapaReclutamientoModel.nombre, func.count(PostulacionModel.id))
        .join(VacanteModel, VacanteModel.id == PostulacionModel.vacante_id)
        .join(EtapaReclutamientoModel, EtapaReclutamientoModel.id == PostulacionModel.etapa_id)
        .where(VacanteModel.empresa_id == empresa_id)
        .group_by(EtapaReclutamientoModel.nombre)
    )
    departamentos = await session.scalar(
        select(func.count()).select_from(DepartamentoModel).where(
            DepartamentoModel.empresa_id == empresa_id
        )
    )
    cargos = await session.scalar(
        select(func.count()).select_from(CargoModel).where(CargoModel.empresa_id == empresa_id)
    )
    return ResumenEmpresa(
        usuarios_activos=conteo_usuarios.get(True, 0),
        usuarios_inactivos=conteo_usuarios.get(False, 0),
        vacantes_por_estado={estado: total for estado, total in vacantes.all()},
        postulaciones_por_etapa={etapa: total for etapa, total in postulaciones.all()},
        departamentos=departamentos or 0,
        cargos=cargos or 0,
    )


async def _resumen_plataforma(session: AsyncSession) -> ResumenPlataforma:
    empresas = await session.execute(
        select(
            func.count().filter(
                EmpresaModel.eliminado_at.is_(None), EmpresaModel.activo.is_(True)
            ),
            func.count().filter(
                EmpresaModel.eliminado_at.is_(None), EmpresaModel.activo.is_(False)
            ),
            func.count().filter(EmpresaModel.eliminado_at.is_not(None)),
        ).select_from(EmpresaModel)
    )
    activas, suspendidas, eliminadas = empresas.one()

    usuarios = await session.scalar(
        select(func.count()).select_from(UserModel).where(UserModel.eliminado_at.is_(None))
    )
    vacantes_publicadas = await session.scalar(
        select(func.count()).select_from(VacanteModel).where(VacanteModel.estado == "PUBLICADA")
    )
    postulaciones_del_mes = await session.scalar(
        select(func.count())
        .select_from(PostulacionModel)
        .where(PostulacionModel.fecha_postulacion >= func.date_trunc("month", func.now()))
    )
    return ResumenPlataforma(
        empresas_activas=activas,
        empresas_suspendidas=suspendidas,
        empresas_eliminadas=eliminadas,
        usuarios_totales=usuarios or 0,
        vacantes_publicadas=vacantes_publicadas or 0,
        postulaciones_del_mes=postulaciones_del_mes or 0,
    )


@router.get(
    "/resumen",
    response_model=ResumenDashboardResponse,
    summary="Consultar resumen del dashboard",
    description=(
        "Devuelve el resumen agregado de la pantalla de inicio. Un usuario de empresa "
        "(permiso `empresa:ver`) recibe los totales de su propia empresa; un "
        "administrador de plataforma (permiso `platform:empresas:ver`) recibe los "
        "totales globales. En ambos casos se incluyen las cinco últimas entradas de "
        "bitácora de la empresa o de todas las empresas para la plataforma."
    ),
)
async def resumen_dashboard(
    user: CurrentUser = Depends(
        require_scoped_permission("empresa:ver", "platform:empresas:ver")
    ),
    session: AsyncSession = Depends(get_session),
) -> ResumenDashboardResponse:
    if user.es_plataforma:
        return ResumenDashboardResponse(
            alcance="PLATAFORMA",
            plataforma=await _resumen_plataforma(session),
            bitacora_reciente=await _bitacora_reciente(session, None),
        )
    return ResumenDashboardResponse(
        alcance="EMPRESA",
        empresa_id=user.empresa_id,
        empresa=await _resumen_empresa(session, user.empresa_id),
        bitacora_reciente=await _bitacora_reciente(session, user.empresa_id),
    )
