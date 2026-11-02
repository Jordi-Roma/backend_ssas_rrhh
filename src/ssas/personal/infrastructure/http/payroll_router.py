"""Payroll periods and payslips; no implicit legal rates."""

from calendar import monthrange
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.core.security.dependencies import (
    CurrentUser,
    require_platform_permission,
    require_scoped_any_permission,
    require_scoped_permission,
)
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.infrastructure.database.session import get_session
from ssas.parametros_legales.infrastructure.persistence.models.parametro_legal import (
    ParametroLegalModel,
    ParametroValorModel,
)
from ssas.personal.application.audit import record_personal_event
from ssas.personal.application.payroll import (
    SEED_RULES,
    PayrollConfigurationError,
    calculate_payroll,
    suggest_calendar_proration,
)
from ssas.personal.application.rc_iva import calculate_rc_iva
from ssas.personal.infrastructure.http.router import self_employee, tenant
from ssas.personal.infrastructure.persistence.models import (
    AsistenciaModel,
    AutorizacionHorasExtraModel,
    BoletaDetalleModel,
    BoletaPagoModel,
    ContratoModel,
    EstructuraSalarialModel,
    HaberProporcionalModel,
    ImpuestoEmpleadoModel,
    PeriodoNominaModel,
    ReglaSalarialModel,
    SolicitudAusenciaModel,
    SolicitudCorreccionAsistenciaModel,
    TipoAusenciaModel,
)

router = APIRouter(prefix="/nomina", tags=["Personal"])

REQUIRED_CONCEPTS = {
    "SALARIO_BASICO",
    "HORAS_EXTRA",
    "AFP",
    "SOLIDARIO",
    "ANS",
    "RC_IVA",
    "CNS_PATRONAL",
    "VIVIENDA_PATRONAL",
    "RIESGO_PATRONAL",
    "SOLIDARIO_PATRONAL",
}


class PeriodInput(BaseModel):
    gestion: int = Field(ge=2000, le=2100)
    mes: int = Field(ge=1, le=12)


class SalaryRuleInput(BaseModel):
    codigo: str = Field(min_length=1, max_length=60)
    nombre: str = Field(min_length=1, max_length=150)
    tipo: str
    secuencia: int = Field(ge=1)
    tipo_calculo: str
    monto_fijo: Decimal | None = Field(default=None, ge=0)
    base_calculo: str | None = None
    parametro_codigo: str | None = None


class TaxWithholdingInput(BaseModel):
    empleado_id: UUID
    rc_iva_retenido: Decimal = Field(ge=0, decimal_places=2)
    referencia_planilla: str = Field(min_length=3, max_length=160)


class TaxDataInput(BaseModel):
    empleado_id: UUID
    f110_credito: Decimal = Field(default=Decimal(0), ge=0, decimal_places=2)
    saldo_favor_anterior: Decimal = Field(default=Decimal(0), ge=0, decimal_places=2)
    mantenimiento_valor: Decimal = Field(default=Decimal(0), ge=0, decimal_places=2)
    saldo_siete_rg: Decimal = Field(default=Decimal(0), ge=0, decimal_places=2)
    f110_siete_rg: Decimal = Field(default=Decimal(0), ge=0, decimal_places=2)
    referencia_planilla: str = Field(min_length=3, max_length=160)


class ProportionalPayInput(BaseModel):
    empleado_id: UUID
    dias_pagados: int = Field(ge=1, le=31)
    haber_basico_pagado: Decimal = Field(gt=0, decimal_places=2)
    referencia_calculo: str = Field(min_length=5, max_length=160)


class LegalRateInput(BaseModel):
    vigente_desde: date
    vigente_hasta: date
    porcentaje: Decimal = Field(ge=0, le=100, decimal_places=4)
    norma_legal: str = Field(min_length=5)


class MinimumWageInput(BaseModel):
    vigente_desde: date
    vigente_hasta: date
    monto: Decimal = Field(gt=0, decimal_places=2)
    norma_legal: str = Field(min_length=5)


@router.post(
    "/salario-minimo", status_code=201, summary="Registrar salario minimo legal verificado"
)
async def create_minimum_wage(
    payload: MinimumWageInput,
    user: CurrentUser = Depends(require_platform_permission("platform:nomina:parametros")),
    session: AsyncSession = Depends(get_session),
):
    if payload.vigente_desde > payload.vigente_hasta:
        raise HTTPException(422, "Vigencia invalida")
    catalog = await session.scalar(
        select(ParametroLegalModel).where(ParametroLegalModel.codigo == "SMN_BO").with_for_update()
    )
    if catalog is None:
        raise HTTPException(409, "El catalogo legal aun no fue migrado")
    overlap = await session.scalar(
        select(ParametroValorModel.id).where(
            ParametroValorModel.parametro_id == catalog.id,
            ParametroValorModel.vigente_desde <= payload.vigente_hasta,
            ParametroValorModel.vigente_hasta >= payload.vigente_desde,
        )
    )
    if overlap:
        raise HTTPException(409, "Ya existe salario minimo para ese intervalo")
    row = ParametroValorModel(
        parametro_id=catalog.id,
        valor={"monto": str(payload.monto)},
        vigente_desde=payload.vigente_desde,
        vigente_hasta=payload.vigente_hasta,
        norma_legal=payload.norma_legal,
    )
    session.add(row)
    await session.flush()
    await record_personal_event(
        session,
        user,
        None,
        action="SMN_REGISTRADO",
        table="parametro_valor",
        record_id=row.id,
        data={"vigente_desde": str(row.vigente_desde)},
    )
    return {"id": row.id, "monto": payload.monto}


@router.get("/parametros-legales", summary="Consultar tasas salariales y vigencias")
async def list_legal_rates(
    user: CurrentUser = Depends(require_platform_permission("platform:nomina:parametros")),
    session: AsyncSession = Depends(get_session),
):
    codes = {row[6] for row in SEED_RULES if row[6]} | {"SMN_BO"}
    rows = (
        await session.execute(
            select(ParametroValorModel, ParametroLegalModel.codigo)
            .join(ParametroLegalModel, ParametroLegalModel.id == ParametroValorModel.parametro_id)
            .where(ParametroLegalModel.codigo.in_(codes))
            .order_by(ParametroValorModel.vigente_desde.desc())
        )
    ).all()
    return [
        {
            "id": r.id,
            "codigo": code,
            "vigente_desde": r.vigente_desde,
            "vigente_hasta": r.vigente_hasta,
            "porcentaje": r.valor.get("porcentaje"),
            "monto": r.valor.get("monto"),
            "norma_legal": r.norma_legal,
        }
        for r, code in rows
    ]


@router.post(
    "/parametros-legales/{codigo}", status_code=201, summary="Registrar tasa legal verificada"
)
async def create_legal_rate(
    codigo: str,
    payload: LegalRateInput,
    user: CurrentUser = Depends(require_platform_permission("platform:nomina:parametros")),
    session: AsyncSession = Depends(get_session),
):
    if codigo not in {row[6] for row in SEED_RULES if row[6]}:
        raise HTTPException(404, "Concepto legal no disponible")
    if payload.vigente_desde > payload.vigente_hasta:
        raise HTTPException(422, "Vigencia invalida")
    catalog = await session.scalar(
        select(ParametroLegalModel).where(ParametroLegalModel.codigo == codigo).with_for_update()
    )
    if catalog is None:
        raise HTTPException(409, "El catalogo legal aun no fue migrado")
    overlap = await session.scalar(
        select(ParametroValorModel.id).where(
            ParametroValorModel.parametro_id == catalog.id,
            ParametroValorModel.vigente_desde <= payload.vigente_hasta,
            ParametroValorModel.vigente_hasta >= payload.vigente_desde,
        )
    )
    if overlap:
        raise HTTPException(409, "Ya existe una tasa para ese intervalo")
    row = ParametroValorModel(
        parametro_id=catalog.id,
        valor={"porcentaje": str(payload.porcentaje)},
        vigente_desde=payload.vigente_desde,
        vigente_hasta=payload.vigente_hasta,
        norma_legal=payload.norma_legal,
    )
    session.add(row)
    await session.flush()
    await record_personal_event(
        session,
        user,
        None,
        action="TASA_LEGAL_CREADA",
        table="parametro_valor",
        record_id=row.id,
        data={
            "codigo": codigo,
            "vigente_desde": str(row.vigente_desde),
            "vigente_hasta": str(row.vigente_hasta),
        },
    )
    return {
        "id": row.id,
        "codigo": codigo,
        "porcentaje": payload.porcentaje,
        "vigente_desde": row.vigente_desde,
        "vigente_hasta": row.vigente_hasta,
    }


@router.get("/estructura", summary="Consultar estructura salarial")
async def salary_structure(
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("nomina:ver", "platform:nomina:ver")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    structure = await session.scalar(
        select(EstructuraSalarialModel).where(
            EstructuraSalarialModel.empresa_id == company,
            EstructuraSalarialModel.activa.is_(True),
        )
    )
    if structure is None:
        return {"estructura": None, "reglas": []}
    rules = (
        await session.scalars(
            select(ReglaSalarialModel)
            .where(
                ReglaSalarialModel.empresa_id == company,
                ReglaSalarialModel.estructura_id == structure.id,
            )
            .order_by(ReglaSalarialModel.secuencia)
        )
    ).all()
    return {
        "estructura": {"id": structure.id, "nombre": structure.nombre},
        "reglas": [
            {
                "id": r.id,
                "codigo": r.codigo,
                "nombre": r.nombre,
                "tipo": r.tipo,
                "secuencia": r.secuencia,
                "tipo_calculo": r.tipo_calculo,
                "monto_fijo": r.monto_fijo,
                "base_calculo": r.base_calculo,
                "parametro_codigo": r.parametro_codigo,
                "activa": r.activa,
            }
            for r in rules
        ],
    }


@router.post("/estructura/reglas", status_code=201, summary="Agregar regla salarial validada")
async def add_salary_rule(
    payload: SalaryRuleInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    if payload.tipo not in {"INGRESO", "DESCUENTO", "PATRONAL"}:
        raise HTTPException(422, "Tipo de regla no admitido")
    if payload.tipo_calculo not in {"BASE", "FIJO", "PORCENTAJE", "EXTERNO", "TRAMOS_ANS_BO"}:
        raise HTTPException(422, "Tipo de calculo no admitido")
    if (payload.codigo == "ANS") != (payload.tipo_calculo == "TRAMOS_ANS_BO"):
        raise HTTPException(422, "ANS requiere calculo por tramos")
    if payload.codigo == "ANS" and payload.tipo != "DESCUENTO":
        raise HTTPException(422, "ANS debe ser un descuento")
    if payload.tipo_calculo == "BASE" and payload.codigo != "SALARIO_BASICO":
        raise HTTPException(422, "BASE solo corresponde al salario basico")
    if payload.tipo_calculo == "FIJO" and payload.monto_fijo is None:
        raise HTTPException(422, "Falta el monto fijo")
    if payload.tipo_calculo == "PORCENTAJE" and (
        not payload.parametro_codigo
        or payload.base_calculo not in {"SALARIO_BASICO", "TOTAL_GANADO"}
    ):
        raise HTTPException(422, "Falta el parametro legal o la base")
    if payload.codigo == "RC_IVA" and (
        payload.tipo_calculo != "EXTERNO" or payload.tipo != "DESCUENTO"
    ):
        raise HTTPException(422, "RC-IVA debe provenir de la planilla tributaria verificada")
    if payload.tipo_calculo == "EXTERNO" and payload.codigo not in {"RC_IVA", "HORAS_EXTRA"}:
        raise HTTPException(422, "Solo RC-IVA y HORAS_EXTRA admiten importe externo")
    if payload.codigo == "HORAS_EXTRA" and (
        payload.tipo_calculo != "EXTERNO" or payload.tipo != "INGRESO"
    ):
        raise HTTPException(422, "HORAS_EXTRA requiere un importe autorizado por RRHH")
    structure = await session.scalar(
        select(EstructuraSalarialModel)
        .where(
            EstructuraSalarialModel.empresa_id == company,
            EstructuraSalarialModel.activa.is_(True),
        )
        .with_for_update()
    )
    if structure is None:
        structure = EstructuraSalarialModel(empresa_id=company, nombre="Nomina general")
        session.add(structure)
        await session.flush()
    duplicate = await session.scalar(
        select(ReglaSalarialModel.id).where(
            ReglaSalarialModel.estructura_id == structure.id,
            or_(
                ReglaSalarialModel.codigo == payload.codigo,
                ReglaSalarialModel.secuencia == payload.secuencia,
            ),
        )
    )
    if duplicate:
        raise HTTPException(409, "Codigo o secuencia ya utilizado")
    row = ReglaSalarialModel(
        empresa_id=company,
        estructura_id=structure.id,
        codigo=payload.codigo,
        nombre=payload.nombre,
        tipo=payload.tipo,
        secuencia=payload.secuencia,
        tipo_calculo=payload.tipo_calculo,
        monto_fijo=payload.monto_fijo,
        base_calculo=payload.base_calculo,
        parametro_codigo=payload.parametro_codigo,
    )
    session.add(row)
    await session.flush()
    await record_personal_event(
        session,
        user,
        company,
        action="REGLA_SALARIAL_CREADA",
        table="regla_salarial",
        record_id=row.id,
        data={"codigo": row.codigo},
    )
    return {"id": row.id, "codigo": row.codigo}


def period_dict(row: PeriodoNominaModel) -> dict:
    return {
        "id": row.id,
        "empresa_id": row.empresa_id,
        "gestion": row.gestion,
        "mes": row.mes,
        "estado": row.estado,
        "calculado_en": row.calculado_en,
        "aprobado_en": row.aprobado_en,
    }


def payslip_dict(row: BoletaPagoModel, details: list[BoletaDetalleModel]) -> dict:
    return {
        "id": row.id,
        "periodo_id": row.periodo_id,
        "empleado_id": row.empleado_id,
        "dias_trabajados": row.dias_trabajados,
        "salario_basico": row.salario_basico,
        "total_ganado": row.total_ganado,
        "total_descuentos": row.total_descuentos,
        "liquido_pagable": row.liquido_pagable,
        "total_aportes_patronales": row.total_aportes_patronales,
        "detalle": [
            {"codigo": d.codigo, "nombre": d.nombre, "tipo": d.tipo, "monto": d.monto}
            for d in details
        ],
    }


async def legal_rates(session: AsyncSession, codes: set[str], cutoff: date) -> dict[str, Decimal]:
    rates = {}
    for code in codes:
        values = (
            (
                await session.execute(
                    select(ParametroValorModel)
                    .join(
                        ParametroLegalModel,
                        ParametroLegalModel.id == ParametroValorModel.parametro_id,
                    )
                    .where(
                        ParametroLegalModel.codigo == code,
                        ParametroValorModel.vigente_desde <= cutoff.replace(day=1),
                        ParametroValorModel.vigente_hasta >= cutoff,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(values) != 1 or not values[0].norma_legal:
            raise PayrollConfigurationError(f"Parametro legal {code} sin vigencia unica o norma")
        raw = values[0].valor.get("porcentaje")
        if raw is None:
            raise PayrollConfigurationError(f"Parametro legal {code} sin porcentaje")
        rates[code] = Decimal(str(raw))
    return rates


async def minimum_wage(session: AsyncSession, cutoff: date) -> Decimal:
    values = (
        await session.scalars(
            select(ParametroValorModel)
            .join(ParametroLegalModel, ParametroLegalModel.id == ParametroValorModel.parametro_id)
            .where(
                ParametroLegalModel.codigo == "SMN_BO",
                ParametroValorModel.vigente_desde <= cutoff.replace(day=1),
                ParametroValorModel.vigente_hasta >= cutoff,
            )
        )
    ).all()
    if len(values) != 1 or not values[0].norma_legal:
        raise PayrollConfigurationError("Salario minimo sin vigencia unica o norma")
    raw = values[0].valor.get("monto")
    if raw is None or Decimal(str(raw)) <= 0:
        raise PayrollConfigurationError("Salario minimo invalido")
    return Decimal(str(raw))


@router.get("/periodos", summary="Listar periodos de nomina")
async def periods(
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_any_permission(
            ("nomina:ver", "nomina:gestionar", "boletas:ver", "boletas:mi"),
            ("platform:nomina:ver", "platform:nomina:gestionar", "platform:boletas:ver"),
        )
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    rows = (
        await session.scalars(
            select(PeriodoNominaModel)
            .where(PeriodoNominaModel.empresa_id == company)
            .order_by(PeriodoNominaModel.gestion.desc(), PeriodoNominaModel.mes.desc())
        )
    ).all()
    return [period_dict(row) for row in rows]


@router.post("/periodos", status_code=201, summary="Abrir periodo de nomina")
async def open_period(
    payload: PeriodInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    existing = await session.scalar(
        select(PeriodoNominaModel.id).where(
            PeriodoNominaModel.empresa_id == company,
            PeriodoNominaModel.gestion == payload.gestion,
            PeriodoNominaModel.mes == payload.mes,
        )
    )
    if existing:
        raise HTTPException(409, "El periodo ya existe")
    row = PeriodoNominaModel(empresa_id=company, gestion=payload.gestion, mes=payload.mes)
    session.add(row)
    await session.flush()
    return period_dict(row)


@router.put(
    "/periodos/{periodo_id}/rc-iva", summary="Registrar importe retenido de planilla tributaria"
)
async def register_tax_withholding(
    periodo_id: UUID,
    payload: TaxWithholdingInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    period = await session.scalar(
        select(PeriodoNominaModel)
        .where(
            PeriodoNominaModel.id == str(periodo_id),
            PeriodoNominaModel.empresa_id == company,
        )
        .with_for_update()
    )
    if period is None:
        raise HTTPException(404, "Periodo no encontrado")
    if period.estado != "ABIERTO":
        raise HTTPException(409, "El importe tributario solo se registra antes de calcular")
    worker = await session.scalar(
        select(EmpleadoModel.id).where(
            EmpleadoModel.id == str(payload.empleado_id), EmpleadoModel.empresa_id == company
        )
    )
    if worker is None:
        raise HTTPException(404, "Empleado no encontrado")
    row = await session.scalar(
        select(ImpuestoEmpleadoModel)
        .where(
            ImpuestoEmpleadoModel.empresa_id == company,
            ImpuestoEmpleadoModel.periodo_id == period.id,
            ImpuestoEmpleadoModel.empleado_id == worker,
        )
        .with_for_update()
    )
    if row is None:
        row = ImpuestoEmpleadoModel(
            empresa_id=company,
            periodo_id=period.id,
            empleado_id=worker,
            rc_iva_retenido=payload.rc_iva_retenido,
            referencia_planilla=payload.referencia_planilla,
            registrado_por_id=user.id,
        )
        session.add(row)
    else:
        row.rc_iva_retenido = payload.rc_iva_retenido
        row.referencia_planilla = payload.referencia_planilla
        row.registrado_por_id = user.id
    row.datos_tributarios = None
    await session.flush()
    await record_personal_event(
        session,
        user,
        company,
        action="RC_IVA_REGISTRADO",
        table="impuesto_empleado",
        record_id=row.id,
        data={"empleado_id": worker, "referencia_planilla": row.referencia_planilla},
    )
    return {
        "id": row.id,
        "empleado_id": worker,
        "rc_iva_retenido": row.rc_iva_retenido,
        "referencia_planilla": row.referencia_planilla,
    }


@router.put(
    "/periodos/{periodo_id}/rc-iva/datos",
    summary="Registrar datos F110 y saldo para calculo automatico RC-IVA",
)
async def register_tax_data(
    periodo_id: UUID,
    payload: TaxDataInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    registered = await register_tax_withholding(
        periodo_id,
        TaxWithholdingInput(
            empleado_id=payload.empleado_id,
            rc_iva_retenido=Decimal(0),
            referencia_planilla=payload.referencia_planilla,
        ),
        empresa_id,
        user,
        session,
    )
    row = await session.get(ImpuestoEmpleadoModel, registered["id"])
    row.datos_tributarios = {
        "f110_credito": str(payload.f110_credito),
        "saldo_favor_anterior": str(payload.saldo_favor_anterior),
        "mantenimiento_valor": str(payload.mantenimiento_valor),
        "saldo_siete_rg": str(payload.saldo_siete_rg),
        "f110_siete_rg": str(payload.f110_siete_rg),
    }
    await record_personal_event(
        session,
        user,
        tenant(user, empresa_id),
        action="DATOS_RC_IVA_REGISTRADOS",
        table="impuesto_empleado",
        record_id=row.id,
        data={"empleado_id": row.empleado_id, "referencia_planilla": row.referencia_planilla},
    )
    return {"id": row.id, "empleado_id": row.empleado_id, "modo": "AUTOMATICO"}


@router.put(
    "/periodos/{periodo_id}/haber-proporcional",
    summary="Registrar haber proporcional revisado para ingreso, salida o ausencia sin goce",
)
async def register_proportional_pay(
    periodo_id: UUID,
    payload: ProportionalPayInput,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    period = await session.scalar(
        select(PeriodoNominaModel)
        .where(PeriodoNominaModel.id == str(periodo_id), PeriodoNominaModel.empresa_id == company)
        .with_for_update()
    )
    if period is None:
        raise HTTPException(404, "Periodo no encontrado")
    if period.estado != "ABIERTO":
        raise HTTPException(409, "El haber proporcional solo se registra antes de calcular")
    if payload.dias_pagados > monthrange(period.gestion, period.mes)[1]:
        raise HTTPException(422, "Los dias pagados exceden la duracion del mes")
    worker = await session.scalar(
        select(EmpleadoModel.id).where(
            EmpleadoModel.id == str(payload.empleado_id), EmpleadoModel.empresa_id == company
        )
    )
    if worker is None:
        raise HTTPException(404, "Empleado no encontrado")
    row = await session.scalar(
        select(HaberProporcionalModel)
        .where(
            HaberProporcionalModel.empresa_id == company,
            HaberProporcionalModel.periodo_id == period.id,
            HaberProporcionalModel.empleado_id == worker,
        )
        .with_for_update()
    )
    if row is None:
        row = HaberProporcionalModel(
            empresa_id=company,
            periodo_id=period.id,
            empleado_id=worker,
            dias_pagados=payload.dias_pagados,
            haber_basico_pagado=payload.haber_basico_pagado,
            referencia_calculo=payload.referencia_calculo,
            registrado_por_id=user.id,
        )
        session.add(row)
    else:
        row.dias_pagados = payload.dias_pagados
        row.haber_basico_pagado = payload.haber_basico_pagado
        row.referencia_calculo = payload.referencia_calculo
        row.registrado_por_id = user.id
    await session.flush()
    await record_personal_event(
        session,
        user,
        company,
        action="HABER_PROPORCIONAL_REGISTRADO",
        table="haber_proporcional",
        record_id=row.id,
        data={"empleado_id": worker, "referencia_calculo": row.referencia_calculo},
    )
    return {
        "id": row.id,
        "empleado_id": worker,
        "dias_pagados": row.dias_pagados,
        "haber_basico_pagado": row.haber_basico_pagado,
        "referencia_calculo": row.referencia_calculo,
    }


@router.get(
    "/periodos/{periodo_id}/haber-proporcional/sugerencia",
    summary="Previsualizar haber proporcional por dias calendario",
)
async def suggest_proportional_pay(
    periodo_id: UUID,
    empleado_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    period = await session.scalar(
        select(PeriodoNominaModel).where(
            PeriodoNominaModel.id == str(periodo_id), PeriodoNominaModel.empresa_id == company
        )
    )
    if period is None:
        raise HTTPException(404, "Periodo no encontrado")
    first = date(period.gestion, period.mes, 1)
    last = date(period.gestion, period.mes, monthrange(period.gestion, period.mes)[1])
    contracts = (
        await session.scalars(
            select(ContratoModel)
            .join(EmpleadoModel, EmpleadoModel.id == ContratoModel.empleado_id)
            .where(
                ContratoModel.empresa_id == company,
                EmpleadoModel.empresa_id == company,
                ContratoModel.empleado_id == str(empleado_id),
                ContratoModel.fecha_inicio <= last,
                or_(ContratoModel.fecha_fin.is_(None), ContratoModel.fecha_fin >= first),
            )
        )
    ).all()
    if len(contracts) != 1:
        raise HTTPException(409, "Se requiere un unico contrato durante el periodo")
    contract = contracts[0]
    leaves = (
        await session.execute(
            select(SolicitudAusenciaModel.fecha_inicio, SolicitudAusenciaModel.fecha_fin)
            .join(
                TipoAusenciaModel, TipoAusenciaModel.id == SolicitudAusenciaModel.tipo_ausencia_id
            )
            .where(
                SolicitudAusenciaModel.empresa_id == company,
                TipoAusenciaModel.empresa_id == company,
                SolicitudAusenciaModel.empleado_id == str(empleado_id),
                SolicitudAusenciaModel.estado == "APROBADA",
                TipoAusenciaModel.es_remunerado.is_(False),
                SolicitudAusenciaModel.fecha_inicio <= last,
                SolicitudAusenciaModel.fecha_fin >= first,
            )
        )
    ).all()
    if (
        contract.fecha_inicio <= first
        and (contract.fecha_fin is None or contract.fecha_fin >= last)
        and not leaves
    ):
        raise HTTPException(409, "El contrato cubre el mes completo sin ausencias sin goce")
    suggestion = suggest_calendar_proration(
        contract.salario_basico,
        first,
        last,
        contract.fecha_inicio,
        contract.fecha_fin,
        list(leaves),
    )
    if suggestion.paid_days == 0:
        raise HTTPException(409, "No hay dias pagables; requiere revision especial de RRHH")
    return {
        "empleado_id": str(empleado_id),
        "dias_pagados_sugeridos": suggestion.paid_days,
        "dias_calendario_mes": suggestion.calendar_days,
        "dias_sin_goce": suggestion.unpaid_days,
        "haber_basico_sugerido": suggestion.basic_pay,
        "criterio": "salario_mensual_por_dias_pagados_sobre_dias_calendario_del_mes",
        "requiere_revision": True,
    }


@router.post("/periodos/{periodo_id}/calcular", summary="Calcular nomina con parametros vigentes")
async def calculate_period(
    periodo_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    period = await session.scalar(
        select(PeriodoNominaModel)
        .where(PeriodoNominaModel.id == str(periodo_id), PeriodoNominaModel.empresa_id == company)
        .with_for_update()
    )
    if period is None:
        raise HTTPException(404, "Periodo no encontrado")
    if period.estado not in ("ABIERTO", "CALCULADO"):
        raise HTTPException(409, "El periodo ya fue aprobado")
    cutoff = date(period.gestion, period.mes, monthrange(period.gestion, period.mes)[1])
    if cutoff >= datetime.now(UTC).date():
        raise HTTPException(409, "Solo se calculan meses cerrados")
    structure = await session.scalar(
        select(EstructuraSalarialModel).where(
            EstructuraSalarialModel.empresa_id == company, EstructuraSalarialModel.activa.is_(True)
        )
    )
    if structure is None:
        raise HTTPException(409, "Falta estructura salarial activa")
    rules = (
        await session.scalars(
            select(ReglaSalarialModel)
            .where(
                ReglaSalarialModel.empresa_id == company,
                ReglaSalarialModel.estructura_id == structure.id,
                ReglaSalarialModel.activa.is_(True),
            )
            .order_by(ReglaSalarialModel.secuencia)
        )
    ).all()
    if not rules:
        raise HTTPException(409, "Faltan reglas salariales")
    if REQUIRED_CONCEPTS - {r.codigo for r in rules}:
        raise HTTPException(
            409, "La estructura salarial no tiene todos los conceptos legales obligatorios"
        )
    if any(r.codigo == "RC_IVA" and r.tipo_calculo != "EXTERNO" for r in rules):
        raise HTTPException(409, "RC-IVA debe provenir de planilla tributaria por empleado")
    if any(
        r.codigo == "HORAS_EXTRA" and (r.tipo != "INGRESO" or r.tipo_calculo != "EXTERNO")
        for r in rules
    ):
        raise HTTPException(409, "HORAS_EXTRA debe provenir de autorizacion de RRHH")
    if any(
        r.codigo == "ANS" and (r.tipo != "DESCUENTO" or r.tipo_calculo != "TRAMOS_ANS_BO")
        for r in rules
    ):
        raise HTTPException(409, "La regla ANS debe calcularse por tramos")
    try:
        rates = await legal_rates(
            session, {r.parametro_codigo for r in rules if r.parametro_codigo}, cutoff
        )
        contracts = (
            await session.scalars(
                select(ContratoModel)
                .join(EmpleadoModel, EmpleadoModel.id == ContratoModel.empleado_id)
                .where(
                    ContratoModel.empresa_id == company,
                    EmpleadoModel.empresa_id == company,
                    ContratoModel.fecha_inicio <= cutoff,
                    or_(
                        ContratoModel.fecha_fin.is_(None),
                        ContratoModel.fecha_fin >= cutoff.replace(day=1),
                    ),
                )
            )
        ).all()
        if len({c.empleado_id for c in contracts}) != len(contracts):
            raise PayrollConfigurationError("Hay contratos solapados al cierre del periodo")
        if not contracts:
            raise PayrollConfigurationError("No hay contratos activos para este periodo")
        employee_ids = [c.empleado_id for c in contracts]
        pending_leave = await session.scalar(
            select(SolicitudAusenciaModel.id).where(
                SolicitudAusenciaModel.empresa_id == company,
                SolicitudAusenciaModel.empleado_id.in_(employee_ids),
                SolicitudAusenciaModel.estado == "PENDIENTE",
                SolicitudAusenciaModel.fecha_inicio <= cutoff,
                SolicitudAusenciaModel.fecha_fin >= cutoff.replace(day=1),
            )
        )
        if pending_leave:
            raise PayrollConfigurationError("Hay ausencias pendientes de decision")
        unpaid_leave = (
            await session.scalars(
                select(SolicitudAusenciaModel)
                .join(
                    TipoAusenciaModel,
                    TipoAusenciaModel.id == SolicitudAusenciaModel.tipo_ausencia_id,
                )
                .where(
                    SolicitudAusenciaModel.empresa_id == company,
                    TipoAusenciaModel.empresa_id == company,
                    SolicitudAusenciaModel.empleado_id.in_(employee_ids),
                    SolicitudAusenciaModel.estado == "APROBADA",
                    TipoAusenciaModel.es_remunerado.is_(False),
                    SolicitudAusenciaModel.fecha_inicio <= cutoff,
                    SolicitudAusenciaModel.fecha_fin >= cutoff.replace(day=1),
                )
            )
        ).all()
        partial_pay = (
            await session.scalars(
                select(HaberProporcionalModel).where(
                    HaberProporcionalModel.empresa_id == company,
                    HaberProporcionalModel.periodo_id == period.id,
                    HaberProporcionalModel.empleado_id.in_(employee_ids),
                )
            )
        ).all()
        pay_by_employee = {row.empleado_id: row for row in partial_pay}
        unpaid_employee_ids = {row.empleado_id for row in unpaid_leave}
        for contract in contracts:
            needs_review = (
                contract.fecha_inicio > cutoff.replace(day=1)
                or contract.fecha_fin is not None
                and contract.fecha_fin < cutoff
                or contract.empleado_id in unpaid_employee_ids
            )
            reviewed = pay_by_employee.get(contract.empleado_id)
            if not needs_review and reviewed is not None:
                raise PayrollConfigurationError("Hay un haber proporcional para un mes completo")
            if needs_review:
                suggestion = suggest_calendar_proration(
                    contract.salario_basico,
                    cutoff.replace(day=1),
                    cutoff,
                    contract.fecha_inicio,
                    contract.fecha_fin,
                    [
                        (row.fecha_inicio, row.fecha_fin)
                        for row in unpaid_leave
                        if row.empleado_id == contract.empleado_id
                    ],
                )
                if suggestion.paid_days == 0 or suggestion.basic_pay <= 0:
                    raise PayrollConfigurationError(
                        "Mes sin dias pagables; requiere revision especial de RRHH"
                    )
                if reviewed is None:
                    reviewed = HaberProporcionalModel(
                        empresa_id=company,
                        periodo_id=period.id,
                        empleado_id=contract.empleado_id,
                        dias_pagados=suggestion.paid_days,
                        haber_basico_pagado=suggestion.basic_pay,
                        referencia_calculo="AUTO_DIAS_CALENDARIO",
                        registrado_por_id=user.id,
                    )
                    session.add(reviewed)
                    pay_by_employee[contract.empleado_id] = reviewed
                    await session.flush()
                    await record_personal_event(
                        session,
                        user,
                        company,
                        action="HABER_PROPORCIONAL_CALCULADO",
                        table="haber_proporcional",
                        record_id=reviewed.id,
                        data={
                            "empleado_id": contract.empleado_id,
                            "dias_pagados": suggestion.paid_days,
                        },
                    )
                if reviewed.dias_pagados > suggestion.paid_days:
                    raise PayrollConfigurationError(
                        "Los dias pagados incluyen dias sin contrato o sin goce"
                    )
                if reviewed.haber_basico_pagado > contract.salario_basico:
                    raise PayrollConfigurationError(
                        "El haber basico revisado supera el salario mensual del contrato"
                    )
        pending_correction = await session.scalar(
            select(SolicitudCorreccionAsistenciaModel.id).where(
                SolicitudCorreccionAsistenciaModel.empresa_id == company,
                SolicitudCorreccionAsistenciaModel.estado == "PENDIENTE",
                SolicitudCorreccionAsistenciaModel.fecha >= cutoff.replace(day=1),
                SolicitudCorreccionAsistenciaModel.fecha <= cutoff,
            )
        )
        if pending_correction:
            raise PayrollConfigurationError("Hay correcciones de asistencia pendientes")
        attendance = (
            await session.scalars(
                select(AsistenciaModel).where(
                    AsistenciaModel.empresa_id == company,
                    AsistenciaModel.empleado_id.in_(employee_ids),
                    AsistenciaModel.fecha >= cutoff.replace(day=1),
                    AsistenciaModel.fecha <= cutoff,
                )
            )
        ).all()
        if any(row.hora_salida is None for row in attendance):
            raise PayrollConfigurationError("Hay fichajes incompletos")
        overtime_rows = (
            await session.scalars(
                select(AutorizacionHorasExtraModel)
                .join(
                    AsistenciaModel, AsistenciaModel.id == AutorizacionHorasExtraModel.asistencia_id
                )
                .where(
                    AutorizacionHorasExtraModel.empresa_id == company,
                    AsistenciaModel.empresa_id == company,
                    AsistenciaModel.fecha >= cutoff.replace(day=1),
                    AsistenciaModel.fecha <= cutoff,
                )
            )
        ).all()
        overtime_by_attendance = {row.asistencia_id: row for row in overtime_rows}
        overtime_amounts = {employee_id: Decimal(0) for employee_id in employee_ids}
        for entry in attendance:
            if entry.horas_extra <= 0:
                continue
            authorization = overtime_by_attendance.get(entry.id)
            if authorization is None or authorization.estado not in {"AUTORIZADO", "RECHAZADO"}:
                raise PayrollConfigurationError("Hay horas extra pendientes de autorizacion")
            if authorization.estado == "AUTORIZADO":
                if (
                    authorization.monto_autorizado is None
                    or authorization.horas_solicitadas > entry.horas_extra
                ):
                    raise PayrollConfigurationError("La autorizacion de horas extra es invalida")
                overtime_amounts[entry.empleado_id] += authorization.monto_autorizado
        taxes = (
            await session.scalars(
                select(ImpuestoEmpleadoModel).where(
                    ImpuestoEmpleadoModel.empresa_id == company,
                    ImpuestoEmpleadoModel.periodo_id == period.id,
                )
            )
        ).all()
        tax_by_employee = {row.empleado_id: row for row in taxes}
        if any(c.empleado_id not in tax_by_employee for c in contracts):
            raise PayrollConfigurationError("Falta importe RC-IVA verificado para un empleado")
        smn = (
            await minimum_wage(session, cutoff)
            if any(row.datos_tributarios is not None for row in taxes)
            else None
        )
        calculated = []
        for contract in contracts:
            tax_row = tax_by_employee[contract.empleado_id]
            base_pay = (
                pay_by_employee[contract.empleado_id].haber_basico_pagado
                if contract.empleado_id in pay_by_employee
                else contract.salario_basico
            )
            external = {
                "RC_IVA": Decimal(0)
                if tax_row.datos_tributarios is not None
                else tax_row.rc_iva_retenido,
                "HORAS_EXTRA": overtime_amounts[contract.empleado_id],
            }
            provisional = calculate_payroll(base_pay, rules, rates, external, period_end=cutoff)
            if tax_row.datos_tributarios is not None:
                data = tax_row.datos_tributarios
                contributions = sum(
                    (
                        line.amount
                        for line in provisional.lines
                        if line.code in {"AFP", "SOLIDARIO", "ANS"}
                    ),
                    Decimal(0),
                )
                tax_result = calculate_rc_iva(
                    period_end=cutoff,
                    total_earned=provisional.gross,
                    labor_contributions=contributions,
                    minimum_wage=smn,
                    f110_credit=Decimal(data["f110_credito"]),
                    prior_credit=Decimal(data["saldo_favor_anterior"]),
                    prior_credit_maintenance=Decimal(data["mantenimiento_valor"]),
                    prior_siete_rg=Decimal(data["saldo_siete_rg"]),
                    f110_siete_rg=Decimal(data["f110_siete_rg"]),
                )
                external["RC_IVA"] = tax_result.withheld
                tax_row.rc_iva_retenido = tax_result.withheld
                tax_row.datos_tributarios = {
                    **data,
                    "saldo_favor_siguiente": str(tax_result.next_credit),
                    "saldo_siete_rg_siguiente": str(tax_result.next_siete_rg),
                }
            result = calculate_payroll(base_pay, rules, rates, external, period_end=cutoff)
            calculated.append((contract, result))
    except (PayrollConfigurationError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    old = (
        await session.scalars(
            select(BoletaPagoModel.id).where(
                BoletaPagoModel.periodo_id == period.id, BoletaPagoModel.empresa_id == company
            )
        )
    ).all()
    if old:
        await session.execute(
            delete(BoletaDetalleModel).where(BoletaDetalleModel.boleta_id.in_(old))
        )
        await session.execute(delete(BoletaPagoModel).where(BoletaPagoModel.id.in_(old)))
    for contract, result in calculated:
        row = BoletaPagoModel(
            empresa_id=company,
            periodo_id=period.id,
            empleado_id=contract.empleado_id,
            contrato_id=contract.id,
            dias_trabajados=pay_by_employee[contract.empleado_id].dias_pagados
            if contract.empleado_id in pay_by_employee
            else 30,
            salario_basico=pay_by_employee[contract.empleado_id].haber_basico_pagado
            if contract.empleado_id in pay_by_employee
            else contract.salario_basico,
            total_ganado=result.gross,
            total_descuentos=result.deductions,
            liquido_pagable=result.net,
            total_aportes_patronales=result.employer_contributions,
        )
        session.add(row)
        await session.flush()
        for line in result.lines:
            rule = next(r for r in rules if r.codigo == line.code)
            session.add(
                BoletaDetalleModel(
                    empresa_id=company,
                    boleta_id=row.id,
                    regla_id=rule.id,
                    codigo=line.code,
                    nombre=line.name,
                    tipo=line.kind,
                    cantidad=Decimal(1),
                    monto=line.amount,
                )
            )
    period.estado = "CALCULADO"
    period.calculado_en = datetime.now(UTC)
    await record_personal_event(
        session,
        user,
        company,
        action="NOMINA_CALCULADA",
        table="periodo_nomina",
        record_id=period.id,
        data={"boletas": len(calculated)},
    )
    return {"periodo": period_dict(period), "boletas": len(calculated)}


@router.post("/periodos/{periodo_id}/aprobar", summary="Aprobar nomina calculada")
async def approve_period(
    periodo_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("nomina:gestionar", "platform:nomina:gestionar")
    ),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    row = await session.scalar(
        select(PeriodoNominaModel)
        .where(PeriodoNominaModel.id == str(periodo_id), PeriodoNominaModel.empresa_id == company)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Periodo no encontrado")
    if row.estado != "CALCULADO":
        raise HTTPException(409, "Se requiere una nomina calculada")
    row.estado = "APROBADO"
    row.aprobado_en = datetime.now(UTC)
    row.aprobado_por_id = user.id
    await record_personal_event(
        session, user, company, action="NOMINA_APROBADA", table="periodo_nomina", record_id=row.id
    )
    return period_dict(row)


@router.get("/periodos/{periodo_id}/boletas", summary="Consultar boletas de un periodo")
async def period_payslips(
    periodo_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("boletas:ver", "platform:boletas:ver")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    period = await session.scalar(
        select(PeriodoNominaModel.id).where(
            PeriodoNominaModel.id == str(periodo_id), PeriodoNominaModel.empresa_id == company
        )
    )
    if period is None:
        raise HTTPException(404, "Periodo no encontrado")
    rows = (
        await session.execute(
            select(BoletaPagoModel, EmpleadoModel)
            .join(
                EmpleadoModel,
                (EmpleadoModel.id == BoletaPagoModel.empleado_id)
                & (EmpleadoModel.empresa_id == BoletaPagoModel.empresa_id),
            )
            .where(BoletaPagoModel.periodo_id == period, BoletaPagoModel.empresa_id == company)
        )
    ).all()
    return [
        {
            "id": payslip.id,
            "empleado_id": payslip.empleado_id,
            "liquido_pagable": payslip.liquido_pagable,
            "empleado_codigo": employee.codigo,
            "empleado_nombre": " ".join(
                filter(None, (employee.nombres, employee.apellido_paterno, employee.apellido_materno))
            ),
        }
        for payslip, employee in rows
    ]


@router.get("/mi/boletas", summary="Consultar mis boletas aprobadas")
async def my_payslips(
    user: CurrentUser = Depends(require_scoped_permission("boletas:mi", "platform:boletas:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    rows = (
        await session.scalars(
            select(BoletaPagoModel)
            .join(PeriodoNominaModel, PeriodoNominaModel.id == BoletaPagoModel.periodo_id)
            .where(
                BoletaPagoModel.empresa_id == user.empresa_id,
                BoletaPagoModel.empleado_id == worker.id,
                PeriodoNominaModel.estado == "APROBADO",
            )
        )
    ).all()
    return [
        {"id": r.id, "periodo_id": r.periodo_id, "liquido_pagable": r.liquido_pagable} for r in rows
    ]


@router.get("/mi/boletas/{boleta_id}", summary="Consultar detalle de mi boleta aprobada")
async def my_payslip_detail(
    boleta_id: UUID,
    user: CurrentUser = Depends(require_scoped_permission("boletas:mi", "platform:boletas:mi")),
    session: AsyncSession = Depends(get_session),
):
    worker = await self_employee(session, user)
    row = await session.scalar(
        select(BoletaPagoModel)
        .join(PeriodoNominaModel, PeriodoNominaModel.id == BoletaPagoModel.periodo_id)
        .where(
            BoletaPagoModel.id == str(boleta_id),
            BoletaPagoModel.empresa_id == user.empresa_id,
            BoletaPagoModel.empleado_id == worker.id,
            PeriodoNominaModel.empresa_id == user.empresa_id,
            PeriodoNominaModel.estado == "APROBADO",
        )
    )
    if row is None:
        raise HTTPException(404, "Boleta no encontrada")
    details = (
        await session.scalars(
            select(BoletaDetalleModel).where(
                BoletaDetalleModel.empresa_id == user.empresa_id,
                BoletaDetalleModel.boleta_id == row.id,
            )
        )
    ).all()
    return payslip_dict(row, details)


@router.get("/boletas/{boleta_id}", summary="Consultar detalle de boleta")
async def payslip_detail(
    boleta_id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(require_scoped_permission("boletas:ver", "platform:boletas:ver")),
    session: AsyncSession = Depends(get_session),
):
    company = tenant(user, empresa_id)
    row = await session.scalar(
        select(BoletaPagoModel).where(
            BoletaPagoModel.id == str(boleta_id), BoletaPagoModel.empresa_id == company
        )
    )
    if row is None:
        raise HTTPException(404, "Boleta no encontrada")
    details = (
        await session.scalars(
            select(BoletaDetalleModel).where(
                BoletaDetalleModel.empresa_id == company, BoletaDetalleModel.boleta_id == row.id
            )
        )
    ).all()
    return payslip_dict(row, details)
