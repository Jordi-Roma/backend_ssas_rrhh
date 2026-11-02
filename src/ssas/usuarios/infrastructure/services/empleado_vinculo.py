"""Asocia una cuenta de empresa con una única ficha de empleado."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.roles.infrastructure.persistence.models.role import RoleModel
from ssas.usuarios.infrastructure.http.schemas import VinculoEmpleadoRequest


async def vincular_empleado(
    session: AsyncSession,
    empresa_id: str | None,
    usuario_id: str,
    role_ids: list[str],
    vinculo: VinculoEmpleadoRequest,
) -> EmpleadoModel:
    if empresa_id is None:
        raise HTTPException(422, "La ficha necesita una empresa")
    # Bloquea la cuenta para serializar intentos de vínculo del mismo usuario.
    usuario = await session.scalar(
        select(UserModel).where(
            UserModel.id == usuario_id, UserModel.empresa_id == empresa_id,
            UserModel.eliminado_at.is_(None),
        ).with_for_update()
    )
    if usuario is None:
        raise HTTPException(404, "Usuario no encontrado en esta empresa")
    employee_role = await session.scalar(select(RoleModel.id).where(
        RoleModel.id.in_(role_ids), RoleModel.empresa_id == empresa_id,
        RoleModel.codigo == "EMPLEADO", RoleModel.is_active.is_(True),
    ))
    if employee_role is None:
        raise HTTPException(422, "Asigna el rol Empleado antes de vincular una ficha")
    existing_link = await session.scalar(select(EmpleadoModel).where(
        EmpleadoModel.empresa_id == empresa_id, EmpleadoModel.usuario_id == usuario_id,
    ).with_for_update())
    if existing_link is not None:
        if vinculo.empleado_id == existing_link.id:
            return existing_link
        raise HTTPException(409, "Este usuario ya tiene una ficha vinculada")

    if vinculo.empleado_id is not None:
        employee = await session.scalar(select(EmpleadoModel).where(
            EmpleadoModel.id == vinculo.empleado_id,
            EmpleadoModel.empresa_id == empresa_id,
        ).with_for_update())
        if employee is None:
            raise HTTPException(404, "Ficha de empleado no encontrada en esta empresa")
        if employee.usuario_id is not None:
            raise HTTPException(409, "La ficha ya está vinculada a otra cuenta")
    else:
        data = vinculo.nueva_ficha
        assert data is not None
        code = data.codigo.strip()
        ci = data.ci.strip()
        duplicate = await session.scalar(select(EmpleadoModel.id).where(
            EmpleadoModel.empresa_id == empresa_id,
            (func.lower(EmpleadoModel.codigo) == code.lower()) |
            (func.lower(EmpleadoModel.ci) == ci.lower()),
        ).limit(1))
        if duplicate is not None:
            raise HTTPException(409, "Ya existe un empleado con ese código o CI; vincula su ficha existente")
        employee = EmpleadoModel(
            id=str(uuid4()), empresa_id=empresa_id, codigo=code,
            nombres=data.nombres.strip(), apellido_paterno=data.apellido_paterno.strip(),
            apellido_materno=data.apellido_materno.strip() if data.apellido_materno else None,
            ci=ci, ci_expedido=data.ci_expedido.strip(),
            fecha_ingreso=data.fecha_ingreso, estado="ACTIVO",
        )
        session.add(employee)
    employee.usuario_id = usuario_id
    await session.flush()
    return employee
