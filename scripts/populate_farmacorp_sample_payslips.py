"""Populate clearly identified sample payroll for Farmacorp; dry run by default.

This does not register tax payments or legally verified September rates. September
amounts intentionally reuse October rates for visual testing only. Never run this
against an actual payroll ledger.
"""

import argparse
import asyncio
from calendar import monthrange
from datetime import date, time
from decimal import Decimal

from sqlalchemy import select

from ssas.cargos.infrastructure.persistence.models.cargo import CargoModel
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.infrastructure.database.session import AsyncSessionLocal, dispose_engine
from ssas.personal.application.payroll import calculate_payroll, suggest_calendar_proration
from ssas.personal.infrastructure.http.payroll_router import legal_rates
from ssas.personal.infrastructure.persistence.models import (
    BoletaDetalleModel,
    BoletaPagoModel,
    ContratoModel,
    EstructuraSalarialModel,
    PeriodoNominaModel,
    ReglaSalarialModel,
)


SALARIES = [Decimal(value) for value in ("3500", "3650", "3900", "4200", "4500", "3550", "3750", "4000", "4300", "4600")]


async def populate(apply: bool) -> None:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            company = await session.scalar(select(EmpresaModel).where(EmpresaModel.nombre_comercial == "Farmacorp"))
            if company is None:
                raise RuntimeError("Farmacorp no existe")
            employees = (await session.scalars(select(EmpleadoModel).where(
                EmpleadoModel.empresa_id == company.id,
                EmpleadoModel.codigo.in_([f"FC26-{number:04d}" for number in range(1, 11)]),
                EmpleadoModel.estado == "ACTIVO",
            ))).all()
            by_code = {employee.codigo: employee for employee in employees}
            if len(by_code) != 10:
                raise RuntimeError("Se requieren las diez fichas FC26-0001 a FC26-0010")
            positions = (await session.scalars(select(CargoModel).where(
                CargoModel.empresa_id == company.id, CargoModel.nombre.like("Auxiliar de %")
            ).order_by(CargoModel.nombre))).all()
            if len(positions) < 5:
                raise RuntimeError("Faltan cargos de Farmacorp")
            structure = await session.scalar(select(EstructuraSalarialModel).where(
                EstructuraSalarialModel.empresa_id == company.id,
                EstructuraSalarialModel.activa.is_(True)))
            if structure is None:
                raise RuntimeError("Falta estructura salarial")
            rules = (await session.scalars(select(ReglaSalarialModel).where(
                ReglaSalarialModel.estructura_id == structure.id,
                ReglaSalarialModel.activa.is_(True)))).all()
            rates = await legal_rates(session, {rule.parametro_codigo for rule in rules if rule.parametro_codigo}, date(2026, 10, 31))
            existing_contracts = (await session.scalars(select(ContratoModel).where(
                ContratoModel.empresa_id == company.id,
                ContratoModel.empleado_id.in_([employee.id for employee in employees])
            ))).all()
            if existing_contracts:
                raise RuntimeError("Ya hay contratos para una ficha de muestra; revisar antes de reintentar")
            periods = {row.mes: row for row in (await session.scalars(select(PeriodoNominaModel).where(
                PeriodoNominaModel.empresa_id == company.id,
                PeriodoNominaModel.gestion == 2026,
                PeriodoNominaModel.mes.in_([9, 10]),
            ))).all()}
            if 9 in periods:
                raise RuntimeError("Septiembre ya tiene periodo; revisar antes de reintentar")
            if 10 not in periods or periods[10].estado != "CALCULADO":
                raise RuntimeError("Octubre debe estar calculado antes de añadir muestras")
            print("PREVIEW: 10 contratos de muestra, 5 boletas septiembre y 10 boletas adicionales octubre")
            print("Septiembre reutiliza porcentajes de octubre exclusivamente como muestra; no tiene validez fiscal")
            if not apply:
                return
            september = PeriodoNominaModel(empresa_id=company.id, gestion=2026, mes=9, estado="APROBADO")
            session.add(september)
            await session.flush()
            for index in range(10):
                employee = by_code[f"FC26-{index + 1:04d}"]
                position = positions[index % len(positions)]
                salary = SALARIES[index]
                contract = ContratoModel(
                    empresa_id=company.id, empleado_id=employee.id,
                    cargo_id=position.id, departamento_id=position.departamento_id,
                    numero_contrato=f"FC-MUESTRA-2026-{index + 1:04d}",
                    tipo_contrato="INDEFINIDO", modalidad="PRESENCIAL", jornada="COMPLETA",
                    hora_entrada_programada=time(8, 0), horas_jornada=Decimal("8"),
                    minutos_descanso=60, salario_basico=salary, moneda="BOB",
                    fecha_inicio=employee.fecha_ingreso, fecha_fin=date(2026, 10, 31),
                    estado="VENCIDO",
                    motivo_cambio="DATOS DE MUESTRA: no acredita relación laboral ni pago",
                )
                session.add(contract)
                await session.flush()
                months = (9, 10) if index < 5 else (10,)
                for month in months:
                    period = september if month == 9 else periods[10]
                    already = await session.scalar(select(BoletaPagoModel.id).where(
                        BoletaPagoModel.periodo_id == period.id,
                        BoletaPagoModel.empleado_id == employee.id))
                    if already:
                        raise RuntimeError("Existe boleta para la ficha de muestra")
                    month_start = date(2026, month, 1)
                    month_end = date(2026, month, monthrange(2026, month)[1])
                    proration = suggest_calendar_proration(salary, month_start, month_end,
                                                            contract.fecha_inicio, None, [])
                    result = calculate_payroll(proration.basic_pay, rules, rates,
                                               {"RC_IVA": Decimal("0"), "HORAS_EXTRA": Decimal("0")},
                                               period_end=month_end)
                    slip = BoletaPagoModel(
                        empresa_id=company.id, periodo_id=period.id, empleado_id=employee.id,
                        contrato_id=contract.id, dias_trabajados=proration.paid_days,
                        salario_basico=proration.basic_pay, total_ganado=result.gross,
                        total_descuentos=result.deductions, liquido_pagable=result.net,
                        total_aportes_patronales=result.employer_contributions,
                    )
                    session.add(slip)
                    await session.flush()
                    for line in result.lines:
                        rule = next(rule for rule in rules if rule.codigo == line.code)
                        session.add(BoletaDetalleModel(
                            empresa_id=company.id, boleta_id=slip.id, regla_id=rule.id,
                            codigo=line.code, nombre=line.name, tipo=line.kind,
                            cantidad=Decimal("1"), monto=line.amount,
                        ))
                    session.add(BoletaDetalleModel(
                        empresa_id=company.id, boleta_id=slip.id, regla_id=None,
                        codigo="DATOS_MUESTRA", nombre="Datos de muestra; sin valor fiscal",
                        tipo="INGRESO", cantidad=Decimal("1"), monto=Decimal("0"),
                    ))
            periods[10].estado = "APROBADO"
            print("CREATED: 10 contratos y 15 boletas de muestra; octubre aprobado")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    options = parser.parse_args()
    try:
        asyncio.run(populate(options.apply))
    finally:
        asyncio.run(dispose_engine())
