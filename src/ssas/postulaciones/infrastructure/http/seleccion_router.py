from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.analisis_cv.infrastructure.persistence.models.analisis_cv import AnalisisCvModel
from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.api.request_metadata import get_client_ip
from ssas.core.security.dependencies import CurrentUser, require_scoped_permission
from ssas.empleados.infrastructure.persistence.models.empleado import EmpleadoModel
from ssas.habilidades.infrastructure.persistence.models.habilidad import HabilidadModel
from ssas.infrastructure.database.session import get_session
from ssas.postulaciones.application.use_cases.gestionar_seleccion import GestionarSeleccion
from ssas.postulaciones.domain.seleccion import SeleccionError
from ssas.postulaciones.infrastructure.http.seleccion_schemas import (
    AgendaResponse,
    AnalisisResponse,
    AsociarRequest,
    BancoRequest,
    CandidatoResponse,
    CompararRequest,
    ContratarRequest,
    EmpleadoResponse,
    EntrevistadorOpcion,
    EntrevistaRequest,
    EntrevistaResponse,
    EstadoEntrevista,
    EstadoRequest,
    EvaluacionRequest,
    EvaluacionResponse,
    EventoResponse,
    OpcionesResponse,
    RankingResponse,
    ResultadoRequest,
    VacanteSeleccionResponse,
)
from ssas.postulaciones.infrastructure.http.tablero_router import _empresa
from ssas.postulaciones.infrastructure.persistence.repositories.seleccion_repository import (
    SeleccionRepository,
)
from ssas.postulantes.infrastructure.http.router import PostulanteResponse
from ssas.roles.infrastructure.persistence.repositories.authorization_repository import (
    SqlAlchemyAuthorizationRepository,
)
from ssas.suscripciones.application.policy import SubscriptionPolicy, SubscriptionPolicyError
from ssas.suscripciones.infrastructure.http.feature_guard import require_plan_feature
from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel
from ssas.vacantes.infrastructure.persistence.models.vacante_habilidad import VacanteHabilidadModel

router = APIRouter(tags=["Selección"])


@router.get("/seleccion/vacantes", response_model=list[VacanteSeleccionResponse])
async def vacantes_para_seleccion(
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(
        require_scoped_permission("postulaciones:ver", "platform:postulaciones:ver")
    ),
    session: AsyncSession = Depends(get_session),
):
    target = repo(session, user, empresa_id).empresa_id
    vacancies = (
        await session.scalars(
            select(VacanteModel)
            .where(VacanteModel.empresa_id == target)
            .order_by(VacanteModel.titulo, VacanteModel.id)
            .limit(500)
        )
    ).all()
    requirements = (
        await session.execute(
            select(
                VacanteHabilidadModel.vacante_id,
                HabilidadModel.nombre,
                VacanteHabilidadModel.nivel_requerido,
                VacanteHabilidadModel.es_obligatorio,
                VacanteHabilidadModel.peso,
            )
            .join(HabilidadModel, HabilidadModel.id == VacanteHabilidadModel.habilidad_id)
            .join(VacanteModel, VacanteModel.id == VacanteHabilidadModel.vacante_id)
            .where(VacanteModel.empresa_id == target)
        )
    ).all()
    by_vacancy: dict[str, list[str]] = {}
    for vacancy_id, name, level, required, weight in requirements:
        by_vacancy.setdefault(vacancy_id, []).append(
            f"{name} ({level}{', obligatorio' if required else ''}, peso {weight})"
        )
    return [
        VacanteSeleccionResponse(id=v.id, titulo=v.titulo, habilidades=by_vacancy.get(v.id, []))
        for v in vacancies
    ]


def permiso(code: str):
    async def guard(
        request: Request,
        user: CurrentUser = Depends(require_scoped_permission(code, f"platform:{code}")),
        session: AsyncSession = Depends(get_session),
    ):
        if request.method != "GET" and not user.es_plataforma:
            try:
                await SubscriptionPolicy(
                    session, settings.subscription_grace_days
                ).require_operational(user.empresa_id)
            except SubscriptionPolicyError as exc:
                raise HTTPException(409, str(exc)) from exc
        return user

    return guard


def repo(session, user, empresa_id):
    return SeleccionRepository(session, _empresa(user, str(empresa_id) if empresa_id else None))


async def selection_visibility(session, user):
    codes = await SqlAlchemyAuthorizationRepository(session).get_user_permission_codes(
        user.id, user.empresa_id
    )
    prefix = "platform:" if user.es_plataforma else ""
    return f"{prefix}entrevistas:ver" in codes, f"{prefix}evaluaciones:ver" in codes


def filter_candidate_records(items, visibility):
    interviews, evaluations = visibility
    for item in items:
        if not interviews:
            item["entrevistas"], item["puntaje_entrevistas"] = [], None
        if not evaluations:
            item["evaluaciones"], item["puntaje_evaluaciones"] = [], None
    return items


async def auditar(
    repository, request, user, table, record_id, description, action="UPDATE", data=None
):
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(repository.session)).execute(
        empresa_id=repository.empresa_id,
        user_id=user.id,
        module="SELECCION",
        action=action,
        description=description,
        affected_table=table,
        record_id=record_id,
        source_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        new_data=data,
    )


@router.get("/entrevistas/opciones", response_model=OpcionesResponse)
async def opciones(
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:ver")),
    session: AsyncSession = Depends(get_session),
):
    return await repo(session, user, empresa_id).opciones()


@router.get("/entrevistas", response_model=AgendaResponse)
async def agenda(
    empresa_id: UUID | None = None,
    estado: EstadoEntrevista | None = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    postulacion_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(permiso("entrevistas:ver")),
    session: AsyncSession = Depends(get_session),
):
    if any(d is not None and d.tzinfo is None for d in (desde, hasta)):
        raise HTTPException(422, "Los filtros de fecha deben incluir zona horaria")
    if desde and hasta and desde > hasta:
        raise HTTPException(422, "El rango de fechas no es válido")
    return await repo(session, user, empresa_id).agenda(
        estado, desde, hasta, str(postulacion_id) if postulacion_id else None, offset, limit
    )


@router.post("/entrevistas", response_model=EntrevistaResponse, status_code=201)
async def crear_entrevista(
    data: EntrevistaRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).guardar_entrevista(data.model_dump())
    await auditar(
        repository,
        request,
        user,
        "entrevista",
        item.id,
        "Entrevista programada",
        "CREATE",
        {"postulacion_id": item.postulacion_id},
    )
    return item


@router.get("/entrevistas/{id}", response_model=EntrevistaResponse)
async def entrevista(
    id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:ver")),
    session: AsyncSession = Depends(get_session),
):
    return await repo(session, user, empresa_id).entrevista(str(id))


@router.patch("/entrevistas/{id}", response_model=EntrevistaResponse)
async def editar_entrevista(
    id: UUID,
    data: EntrevistaRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).guardar_entrevista(data.model_dump(), str(id))
    await auditar(repository, request, user, "entrevista", item.id, "Entrevista reprogramada")
    return item


@router.patch("/entrevistas/{id}/estado", response_model=EntrevistaResponse)
async def estado_entrevista(
    id: UUID,
    data: EstadoRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).estado_entrevista(str(id), data.estado)
    await auditar(
        repository, request, user, "entrevista", item.id, f"Entrevista {data.estado.lower()}"
    )
    return item


@router.patch("/entrevistas/{id}/resultado", response_model=EntrevistaResponse)
async def resultado(
    id: UUID,
    data: ResultadoRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:registrar_resultado")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).resultado_entrevista(str(id), data.model_dump())
    await auditar(
        repository, request, user, "entrevista", item.id, "Resultado de entrevista registrado"
    )
    return item


@router.get("/postulaciones/{id}/entrevistas", response_model=list[EntrevistaResponse])
async def entrevistas_postulacion(
    id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("entrevistas:ver")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    await repository.postulacion(str(id))
    return (await repository.agenda(None, None, None, str(id), 0, 100))["items"]


@router.get("/postulaciones/{id}/evaluaciones", response_model=list[EvaluacionResponse])
async def evaluaciones(
    id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("evaluaciones:ver")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    await repository.postulacion(str(id))
    return await repository.evaluaciones([str(id)])


@router.get("/evaluaciones/opciones", response_model=list[EntrevistadorOpcion])
async def evaluadores(
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("evaluaciones:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    return await repo(session, user, empresa_id).responsables("evaluaciones:gestionar")


@router.post("/postulaciones/{id}/evaluaciones", response_model=EvaluacionResponse, status_code=201)
async def crear_evaluacion(
    id: UUID,
    data: EvaluacionRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("evaluaciones:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    evaluador = str(data.evaluador_id) if data.evaluador_id else user.id
    if user.es_plataforma and data.evaluador_id is None:
        raise HTTPException(422, "Selecciona un evaluador de la empresa")
    if not user.es_plataforma and evaluador != user.id:
        raise HTTPException(403, "Debes registrar la evaluación con tu propia identidad")
    await repository.responsable(evaluador, "evaluaciones:gestionar")
    item = await GestionarSeleccion(repository).guardar_evaluacion(
        str(id), data.model_dump(exclude={"evaluador_id"}), evaluador
    )
    await auditar(
        repository, request, user, "evaluacion", item.id, "Evaluación registrada", "CREATE"
    )
    return item


@router.patch("/evaluaciones/{id}", response_model=EvaluacionResponse)
async def editar_evaluacion(
    id: UUID,
    data: EvaluacionRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("evaluaciones:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    original = await repository.evaluacion(str(id))
    if data.evaluador_id is not None and str(data.evaluador_id) != original.evaluador_id:
        raise HTTPException(409, "La corrección no puede cambiar el evaluador original")
    item = await GestionarSeleccion(repository).guardar_evaluacion(
        original.postulacion_id, data.model_dump(exclude={"evaluador_id"}), user.id, str(id)
    )
    await auditar(repository, request, user, "evaluacion", item.id, "Evaluación corregida")
    return item


@router.get("/postulaciones/{id}/analisis-cv", response_model=list[AnalisisResponse])
async def analisis(
    id: UUID,
    empresa_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(permiso("postulaciones:ver")),
    session: AsyncSession = Depends(get_session),
):
    await repo(session, user, empresa_id).postulacion(str(id))
    return (
        await session.scalars(
            select(AnalisisCvModel)
            .where(AnalisisCvModel.postulacion_id == str(id))
            .order_by(AnalisisCvModel.fecha_analisis.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()


@router.post("/postulaciones/{id}/analisis-cv", response_model=AnalisisResponse, status_code=201)
async def analizar(
    id: UUID,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("postulaciones:analizar_cv")),
    session: AsyncSession = Depends(get_session),
):
    from ssas.analisis_cv.application.use_cases.analizar_cv import analizar_cv

    repository = repo(session, user, empresa_id)
    await require_plan_feature(session, repository.empresa_id, "analisis_cv_ia")
    item = await analizar_cv(
        session,
        str(id),
        repository.empresa_id,
        user.id,
        source_ip=get_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    return item


@router.get("/vacantes/{id}/ranking", response_model=RankingResponse)
async def ranking(
    id: UUID,
    empresa_id: UUID | None = None,
    estado: str | None = None,
    orden: str = Query("ia", pattern="^(ia|manual|evaluaciones|entrevistas)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(permiso("postulaciones:ver")),
    session: AsyncSession = Depends(get_session),
):
    items = await repo(session, user, empresa_id).candidatos(str(id))
    visibility = await selection_visibility(session, user)
    if (orden == "entrevistas" and not visibility[0]) or (
        orden == "evaluaciones" and not visibility[1]
    ):
        raise HTTPException(403, "No tienes permiso para ordenar por esos resultados")
    filter_candidate_records(items, visibility)
    if estado:
        items = [item for item in items if item["estado"] == estado]
    field = f"puntaje_{orden}"
    items.sort(key=lambda x: (x[field] is None, -(x[field] or 0), x["_fecha"], x["id"]))
    return {"items": items[offset : offset + limit], "total": len(items)}


@router.post("/vacantes/{id}/comparar", response_model=list[CandidatoResponse])
async def comparar(
    id: UUID,
    data: CompararRequest,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("postulaciones:ver")),
    session: AsyncSession = Depends(get_session),
):
    items = await repo(session, user, empresa_id).candidatos(
        str(id), [str(i) for i in data.postulacion_ids]
    )
    return filter_candidate_records(items, await selection_visibility(session, user))


@router.post("/postulaciones/{id}/contratar", response_model=EmpleadoResponse, status_code=201)
async def contratar(
    id: UUID,
    data: ContratarRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("postulaciones:contratar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).contratar(str(id), data.model_dump())
    await auditar(
        repository,
        request,
        user,
        "postulacion",
        str(id),
        "Postulante contratado",
        "APPROVE",
        {"empleado_id": item.id},
    )
    return item


@router.get("/empleados", response_model=list[EmpleadoResponse])
async def empleados(
    empresa_id: UUID | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    user: CurrentUser = Depends(permiso("empleados:ver")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    return (
        await session.scalars(
            select(EmpleadoModel)
            .where(EmpleadoModel.empresa_id == repository.empresa_id)
            .order_by(EmpleadoModel.fecha_ingreso.desc(), EmpleadoModel.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()


@router.get("/empleados/{id}", response_model=EmpleadoResponse)
async def empleado(
    id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("empleados:ver")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await session.scalar(
        select(EmpleadoModel).where(
            EmpleadoModel.empresa_id == repository.empresa_id, EmpleadoModel.id == str(id)
        )
    )
    if item is None:
        raise SeleccionError("Empleado no encontrado", 404)
    return item


@router.patch("/postulantes/{id}/banco-talento", response_model=PostulanteResponse)
async def banco(
    id: UUID,
    data: BancoRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("postulantes:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).banco(str(id), data.en_banco_talento)
    await auditar(repository, request, user, "postulante", item.id, "Banco de talentos actualizado")
    return item


@router.post("/postulantes/{id}/postulaciones")
async def asociar(
    id: UUID,
    data: AsociarRequest,
    request: Request,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("postulantes:gestionar")),
    session: AsyncSession = Depends(get_session),
):
    repository = repo(session, user, empresa_id)
    item = await GestionarSeleccion(repository).asociar(str(id), str(data.vacante_id))
    await auditar(
        repository,
        request,
        user,
        "postulacion",
        item.id,
        "Postulante del banco asociado a vacante",
        "CREATE",
    )
    return {"id": item.id, "vacante_id": item.vacante_id, "estado": item.estado}


@router.get("/postulaciones/{id}/historial", response_model=list[EventoResponse])
async def historial(
    id: UUID,
    empresa_id: UUID | None = None,
    user: CurrentUser = Depends(permiso("postulaciones:ver")),
    session: AsyncSession = Depends(get_session),
):
    items = await repo(session, user, empresa_id).historial(str(id))
    interviews, evaluations = await selection_visibility(session, user)
    return [
        item
        for item in items
        if (interviews or item["tipo"] != "ENTREVISTA")
        and (evaluations or item["tipo"] != "EVALUACION")
    ]


for route in router.routes:
    if not route.description:
        route.description = (
            f"{route.name.replace('_', ' ').capitalize()} dentro de la empresa autorizada. "
            "Requiere permiso específico; plataforma debe indicar empresa_id."
        )
