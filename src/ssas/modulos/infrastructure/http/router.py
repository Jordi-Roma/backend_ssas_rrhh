from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.core.api.openapi import AUTHENTICATED_RESPONSES, TAG_MODULOS
from ssas.core.security.dependencies import (
    CurrentUser,
    get_current_user,
    require_empresa_permission,
    require_platform_permission,
)
from ssas.infrastructure.database.session import get_session
from ssas.modulos.infrastructure.persistence.models.empresa_modulo import EmpresaModuloModel
from ssas.modulos.infrastructure.persistence.models.modulo import ModuloModel

router = APIRouter(prefix="/modulos", tags=[TAG_MODULOS])
empresa_router = APIRouter(prefix="/empresas", tags=[TAG_MODULOS])


class ModuloResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    codigo: str
    nombre: str
    descripcion: str | None = None
    icono: str | None = None
    orden: int
    es_core: bool
    activo: bool


class ModuloEmpresaResponse(ModuloResponse):
    habilitado: bool
    fecha_habilitacion: datetime | None = None


class ActualizarModulosRequest(BaseModel):
    """Conjunto completo de módulos habilitados: lo que no venga queda deshabilitado."""

    modulos: list[str] = Field(
        description="Códigos de módulo habilitados para la empresa.",
        examples=[["ORGANIZACION", "RECLUTAMIENTO"]],
    )


async def _catalogo(session: AsyncSession) -> list[ModuloModel]:
    result = await session.execute(
        select(ModuloModel).where(ModuloModel.activo.is_(True)).order_by(ModuloModel.orden)
    )
    return list(result.scalars().all())


async def _modulos_de_empresa(
    session: AsyncSession, empresa_id: str
) -> list[ModuloEmpresaResponse]:
    result = await session.execute(
        select(ModuloModel, EmpresaModuloModel)
        .outerjoin(
            EmpresaModuloModel,
            and_(
                EmpresaModuloModel.modulo_id == ModuloModel.id,
                EmpresaModuloModel.empresa_id == empresa_id,
            ),
        )
        .where(ModuloModel.activo.is_(True))
        .order_by(ModuloModel.orden)
    )
    return [
        ModuloEmpresaResponse(
            **ModuloResponse.model_validate(modulo).model_dump(),
            habilitado=modulo.es_core or bool(asignacion and asignacion.habilitado),
            fecha_habilitacion=asignacion.fecha_habilitacion if asignacion else None,
        )
        for modulo, asignacion in result.all()
    ]


@router.get(
    "",
    response_model=list[ModuloResponse],
    summary="Catálogo de módulos",
    description=(
        "Catálogo global de módulos de la plataforma. Es información de producto, "
        "disponible para cualquier identidad autenticada."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def listar_modulos(
    _user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    return await _catalogo(session)


@empresa_router.get(
    "/{empresa_id}/modulos",
    response_model=list[ModuloEmpresaResponse],
    summary="Módulos de una empresa",
    description=(
        "Catálogo con el estado de habilitación de cada módulo para la empresa indicada. "
        "Los módulos núcleo aparecen siempre habilitados."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def listar_modulos_de_empresa(
    empresa_id: str,
    _user: CurrentUser = Depends(require_empresa_permission("empresa:ver", "platform:modulos:ver")),
    session: AsyncSession = Depends(get_session),
):
    return await _modulos_de_empresa(session, empresa_id)


@empresa_router.put(
    "/{empresa_id}/modulos",
    response_model=list[ModuloEmpresaResponse],
    summary="Habilitar módulos de una empresa",
    description=(
        "Reemplaza el conjunto de módulos habilitados. Los módulos núcleo no se pueden "
        "deshabilitar. Operación exclusiva de administradores de la plataforma."
    ),
    responses=AUTHENTICATED_RESPONSES,
)
async def actualizar_modulos_de_empresa(
    empresa_id: str,
    request: ActualizarModulosRequest,
    user: CurrentUser = Depends(require_platform_permission("platform:modulos:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    catalogo = await _catalogo(session)
    por_codigo = {modulo.codigo: modulo for modulo in catalogo}
    solicitados = set(request.modulos)
    desconocidos = sorted(solicitados - por_codigo.keys())
    if desconocidos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Módulos inexistentes: {', '.join(desconocidos)}",
        )

    existentes = {
        asignacion.modulo_id: asignacion
        for asignacion in (
            await session.execute(
                select(EmpresaModuloModel).where(EmpresaModuloModel.empresa_id == empresa_id)
            )
        )
        .scalars()
        .all()
    }
    ahora = datetime.now(UTC)
    for modulo in catalogo:
        habilitado = modulo.es_core or modulo.codigo in solicitados
        asignacion = existentes.get(modulo.id)
        if asignacion is None:
            session.add(
                EmpresaModuloModel(
                    empresa_id=empresa_id,
                    modulo_id=modulo.id,
                    habilitado=habilitado,
                    fecha_habilitacion=ahora if habilitado else None,
                    habilitado_por_id=user.id,
                )
            )
        elif asignacion.habilitado != habilitado:
            asignacion.habilitado = habilitado
            asignacion.fecha_habilitacion = ahora if habilitado else None
            asignacion.habilitado_por_id = user.id
    await session.flush()
    return await _modulos_de_empresa(session, empresa_id)
