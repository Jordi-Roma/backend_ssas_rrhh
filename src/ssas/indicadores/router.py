from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.infrastructure.database.session import get_session

router = APIRouter(prefix="/indicadores", tags=["Indicadores"])


def weekdays(start: date, end: date) -> int:
    return sum((start + timedelta(days=i)).weekday() < 5 for i in range((end - start).days + 1))


@router.get("", summary="Indicadores de recursos humanos por empresa")
async def indicadores(
    desde: date = Query(...), hasta: date = Query(...), empresa_id: str | None = None,
    user: CurrentUser = Depends(require_scoped_permission("indicadores:ver", "platform:indicadores:ver")),
    session: AsyncSession = Depends(get_session),
):
    if hasta < desde or (hasta - desde).days > 366:
        raise HTTPException(422, "El rango debe ser de 1 a 367 días")
    target = empresa_id if user.es_plataforma else user.empresa_id
    if not target or (empresa_id and not user.es_plataforma and empresa_id != target):
        raise HTTPException(403, "Empresa no autorizada")
    args = {"empresa": target, "desde": desde, "hasta": hasta}

    async def one(sql):
        return (await session.execute(text(sql), args)).one()

    opening = (await one("SELECT count(*) FROM empleado WHERE empresa_id=:empresa AND fecha_ingreso<:desde AND (fecha_salida IS NULL OR fecha_salida>=:desde)"))[0]
    closing = (await one("SELECT count(*) FROM empleado WHERE empresa_id=:empresa AND fecha_ingreso<=:hasta AND (fecha_salida IS NULL OR fecha_salida>:hasta)"))[0]
    hires = (await one("SELECT count(*) FROM empleado WHERE empresa_id=:empresa AND fecha_ingreso BETWEEN :desde AND :hasta"))[0]
    exits = (await one("SELECT count(*) FROM empleado WHERE empresa_id=:empresa AND fecha_salida BETWEEN :desde AND :hasta"))[0]
    average_headcount = (opening + closing) / 2
    rotation = round(exits * 100 / average_headcount, 2) if average_headcount else 0
    absence_days = (await one("SELECT coalesce(sum(dias_solicitados),0) FROM solicitud_ausencia WHERE empresa_id=:empresa AND estado='APROBADA' AND fecha_inicio<=:hasta AND fecha_fin>=:desde"))[0]
    # Se acota cada solicitud al rango antes de sumar días laborables reales.
    absence_rows = (await session.execute(text("SELECT fecha_inicio,fecha_fin FROM solicitud_ausencia WHERE empresa_id=:empresa AND estado='APROBADA' AND fecha_inicio<=:hasta AND fecha_fin>=:desde"), args)).all()
    absent_workdays = sum(weekdays(max(a, desde), min(b, hasta)) for a, b in absence_rows)
    working_capacity = weekdays(desde, hasta) * average_headcount
    absenteeism = round(absent_workdays * 100 / working_capacity, 2) if working_capacity else 0
    hiring = (await one("SELECT count(*), avg(e.fecha_ingreso - p.fecha_postulacion::date) FROM postulacion p JOIN vacante v ON v.id=p.vacante_id AND v.empresa_id=:empresa JOIN empleado e ON e.id=p.empleado_id AND e.empresa_id=:empresa WHERE p.estado='CONTRATADA' AND e.fecha_ingreso BETWEEN :desde AND :hasta"))
    departments = (await session.execute(text("SELECT d.id,d.nombre,count(DISTINCT e.id) AS empleados FROM departamento d LEFT JOIN contrato c ON c.departamento_id=d.id AND c.empresa_id=:empresa AND c.estado='VIGENTE' AND c.fecha_inicio<=:hasta AND (c.fecha_fin IS NULL OR c.fecha_fin>=:hasta) LEFT JOIN empleado e ON e.id=c.empleado_id AND e.empresa_id=:empresa AND e.fecha_ingreso<=:hasta AND (e.fecha_salida IS NULL OR e.fecha_salida>:hasta) WHERE d.empresa_id=:empresa GROUP BY d.id,d.nombre ORDER BY d.nombre"), args)).all()
    funnel = (await session.execute(text("SELECT p.estado,count(*) FROM postulacion p JOIN vacante v ON v.id=p.vacante_id WHERE v.empresa_id=:empresa AND p.fecha_postulacion::date BETWEEN :desde AND :hasta GROUP BY p.estado"), args)).all()
    funnel_stages = (await session.execute(text("SELECT etapa.id, etapa.nombre, etapa.orden, count(p.id) FROM etapa_reclutamiento etapa LEFT JOIN postulacion p ON p.etapa_id=etapa.id AND p.fecha_postulacion::date BETWEEN :desde AND :hasta WHERE etapa.empresa_id=:empresa GROUP BY etapa.id, etapa.nombre, etapa.orden ORDER BY etapa.orden"), args)).all()
    return {
        "empresa_id": target, "desde": desde, "hasta": hasta,
        "rotacion": {"porcentaje": rotation, "salidas": exits, "ingresos": hires, "dotacion_inicial": opening, "dotacion_final": closing},
        "ausentismo": {"porcentaje": absenteeism, "dias_habiles_ausentes": absent_workdays, "dias_solicitados": int(absence_days), "dias_habiles_posibles": working_capacity},
        "tiempo_promedio_contratacion": {"dias": round(float(hiring[1]), 2) if hiring[1] is not None else None, "contrataciones_medir": hiring[0]},
        "headcount_por_departamento": [{"departamento_id": str(d), "departamento": n, "empleados": count} for d, n, count in departments],
        "embudo_reclutamiento": {state: count for state, count in funnel},
        "embudo_por_etapa": [{"etapa_id": str(stage_id), "etapa": name, "orden": order, "postulaciones": count} for stage_id, name, order, count in funnel_stages],
    }
