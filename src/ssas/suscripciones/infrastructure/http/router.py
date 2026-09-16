import asyncio
from datetime import UTC, datetime

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.bitacora.application.use_cases.register_audit_event import RegisterAuditEvent
from ssas.bitacora.infrastructure.persistence.repositories.audit_log_repository import (
    SqlAlchemyAuditLogRepository,
)
from ssas.config.settings import settings
from ssas.core.security.dependencies import (
    CurrentUser,
    get_current_user,
    require_platform_permission,
    require_scoped_permission,
)
from ssas.empresas.infrastructure.persistence.models.empresa import EmpresaModel
from ssas.empresas.infrastructure.persistence.models.suscripcion import (
    PlanSuscripcionModel,
    SuscripcionModel,
)
from ssas.infrastructure.database.session import get_session
from ssas.modulos.infrastructure.persistence.models.empresa_modulo import EmpresaModuloModel
from ssas.modulos.infrastructure.persistence.models.modulo import ModuloModel
from ssas.suscripciones.application.policy import SubscriptionPolicy, SubscriptionPolicyError
from ssas.suscripciones.infrastructure.http.schemas import (
    AssignSubscriptionRequest,
    CheckoutRequest,
    ConsumptionResponse,
    PlanRequest,
    PlanResponse,
    RedirectResponse,
    SubscriptionResponse,
)
from ssas.suscripciones.infrastructure.persistence.models.saas import (
    PlanModuloModel,
    StripeEventoModel,
)

plans_router = APIRouter(prefix="/planes", tags=["Planes y suscripciones"])
router = APIRouter(prefix="/suscripcion", tags=["Planes y suscripciones"])
webhook_router = APIRouter(prefix="/webhooks", tags=["Planes y suscripciones"])


def _stripe_ready(webhook: bool = False) -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe Sandbox no está configurado")
    if webhook and not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="El secreto del webhook no está configurado")
    if not webhook and not all(
        (
            settings.stripe_checkout_success_url,
            settings.stripe_checkout_cancel_url,
            settings.stripe_portal_return_url,
        )
    ):
        raise HTTPException(status_code=503, detail="Las URL de retorno de Stripe no están configuradas")
    stripe.api_key = settings.stripe_secret_key


async def _plan_payload(session: AsyncSession, plan: PlanSuscripcionModel) -> dict:
    codes = (await session.execute(select(ModuloModel.codigo).join(PlanModuloModel, PlanModuloModel.modulo_id == ModuloModel.id).where(PlanModuloModel.plan_id == plan.id))).scalars().all()
    return {"id": plan.id, "nombre": plan.nombre, "descripcion": plan.descripcion, "precio_mensual": plan.precio_mensual, "moneda": plan.moneda, "max_usuarios": plan.max_usuarios, "max_vacantes_activas": plan.max_vacantes_activas, "max_almacenamiento_mb": plan.max_almacenamiento_mb, "stripe_price_id": plan.stripe_price_id, "modulos": list(codes), "activo": plan.activo}


async def _subscription_payload(session: AsyncSession, item: SuscripcionModel) -> dict:
    plan = await session.get(PlanSuscripcionModel, item.plan_id)
    return {"id": item.id, "empresa_id": item.empresa_id, "plan": await _plan_payload(session, plan), "estado": item.estado, "fecha_inicio": item.fecha_inicio, "fecha_fin": item.fecha_fin, "periodo_prueba_hasta": item.periodo_prueba_hasta, "cancelar_al_fin_periodo": item.cancelar_al_fin_periodo, "fecha_ultimo_pago": item.fecha_ultimo_pago, "fecha_proximo_cobro": item.fecha_proximo_cobro, "stripe_customer_id": item.stripe_customer_id, "stripe_subscription_id": item.stripe_subscription_id}


async def _audit(session: AsyncSession, user_id: str | None, action: str, description: str, record_id: str | None = None, empresa_id: str | None = None, data: dict | None = None) -> None:
    await RegisterAuditEvent(SqlAlchemyAuditLogRepository(session)).execute(empresa_id=empresa_id, module="SUSCRIPCION", action=action, description=description, user_id=user_id, affected_table="suscripcion", record_id=record_id, new_data=data)


async def _sync_modules(session: AsyncSession, empresa_id: str, plan_id: str) -> None:
    module_ids = set((await session.execute(select(PlanModuloModel.modulo_id).where(PlanModuloModel.plan_id == plan_id))).scalars().all())
    modules = (await session.execute(select(ModuloModel))).scalars().all()
    for module in modules:
        row = await session.get(EmpresaModuloModel, (empresa_id, module.id))
        enabled = module.es_core or module.id in module_ids
        if row is None:
            session.add(EmpresaModuloModel(empresa_id=empresa_id, modulo_id=module.id, habilitado=enabled, fecha_habilitacion=datetime.now(UTC) if enabled else None))
        else:
            row.habilitado = enabled


@plans_router.get("", response_model=list[PlanResponse], summary="Listar planes", description="Lista los planes SaaS activos; plataforma puede incluir inactivos.")
async def list_plans(include_inactive: bool = False, _user: CurrentUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    query = select(PlanSuscripcionModel).order_by(PlanSuscripcionModel.precio_mensual)
    if not include_inactive or not _user.es_plataforma:
        query = query.where(PlanSuscripcionModel.activo.is_(True))
    return [await _plan_payload(session, item) for item in (await session.execute(query)).scalars().all()]


@plans_router.post("", response_model=PlanResponse, status_code=201, summary="Crear plan", description="Crea un plan global con límites y módulos contratables.")
async def create_plan(body: PlanRequest, user: CurrentUser = Depends(require_platform_permission("platform:planes:crear")), session: AsyncSession = Depends(get_session)):
    plan = PlanSuscripcionModel(nombre=body.nombre.strip(), descripcion=body.descripcion, precio_mensual=body.precio_mensual, max_empleados=body.max_usuarios, moneda=body.moneda.upper(), max_usuarios=body.max_usuarios, max_vacantes_activas=body.max_vacantes_activas, max_almacenamiento_mb=body.max_almacenamiento_mb, stripe_price_id=body.stripe_price_id, modulos=body.modulos, activo=body.activo)
    session.add(plan); await session.flush()
    ids = (await session.execute(select(ModuloModel.id).where(ModuloModel.codigo.in_(body.modulos)))).scalars().all()
    session.add_all([PlanModuloModel(plan_id=plan.id, modulo_id=i) for i in ids])
    await _audit(session, user.id, "PLAN_CREATED", "Plan SaaS creado", plan.id, data={"nombre": plan.nombre})
    return await _plan_payload(session, plan)


@plans_router.put("/{plan_id}", response_model=PlanResponse, summary="Actualizar plan", description="Actualiza precio, límites, módulos y Price ID de Sandbox.")
async def update_plan(plan_id: str, body: PlanRequest, user: CurrentUser = Depends(require_platform_permission("platform:planes:editar")), session: AsyncSession = Depends(get_session)):
    plan = await session.get(PlanSuscripcionModel, plan_id)
    if not plan: raise HTTPException(404, "Plan no encontrado")
    for key, value in body.model_dump(exclude={"modulos"}).items(): setattr(plan, key, value)
    plan.max_empleados = body.max_usuarios; plan.moneda = body.moneda.upper(); plan.modulos = body.modulos
    await session.execute(PlanModuloModel.__table__.delete().where(PlanModuloModel.plan_id == plan.id))
    ids = (await session.execute(select(ModuloModel.id).where(ModuloModel.codigo.in_(body.modulos)))).scalars().all()
    session.add_all([PlanModuloModel(plan_id=plan.id, modulo_id=i) for i in ids])
    await _audit(session, user.id, "PLAN_UPDATED", "Plan SaaS actualizado", plan.id, data={"nombre": plan.nombre})
    await session.flush(); return await _plan_payload(session, plan)


async def _target_subscription(session: AsyncSession, empresa_id: str) -> SuscripcionModel:
    item = (await session.execute(select(SuscripcionModel).where(SuscripcionModel.empresa_id == empresa_id))).scalar_one_or_none()
    if item is None: raise HTTPException(404, "Suscripción no encontrada")
    return item


@router.get("", response_model=SubscriptionResponse, summary="Consultar mi suscripción", description="Devuelve plan, vigencia y estado del tenant autenticado.")
async def get_subscription(empresa_id: str | None = Query(None), user: CurrentUser = Depends(require_scoped_permission("suscripcion:ver", "platform:suscripciones:ver")), session: AsyncSession = Depends(get_session)):
    target = empresa_id if user.es_plataforma else user.empresa_id
    if not target: raise HTTPException(422, "Debe indicar empresa_id")
    return await _subscription_payload(session, await _target_subscription(session, target))


@router.get("/consumo", response_model=ConsumptionResponse, summary="Consultar consumo", description="Calcula usuarios, vacantes activas y almacenamiento del tenant.")
async def get_consumption(user: CurrentUser = Depends(require_scoped_permission("suscripcion:ver", "platform:suscripciones:ver")), session: AsyncSession = Depends(get_session)):
    if not user.empresa_id: raise HTTPException(403, "Esta vista corresponde a una empresa")
    try: return await SubscriptionPolicy(session, settings.subscription_grace_days).consumption(user.empresa_id)
    except SubscriptionPolicyError as exc: raise HTTPException(409, str(exc)) from exc


@router.put("/empresas/{empresa_id}", response_model=SubscriptionResponse, summary="Ajustar suscripción", description="Permite a plataforma asignar un plan o estado manualmente.")
async def assign_subscription(empresa_id: str, body: AssignSubscriptionRequest, user: CurrentUser = Depends(require_platform_permission("platform:suscripciones:gestionar")), session: AsyncSession = Depends(get_session)):
    plan = await session.get(PlanSuscripcionModel, body.plan_id)
    if not plan: raise HTTPException(404, "Plan no encontrado")
    item = (await session.execute(select(SuscripcionModel).where(SuscripcionModel.empresa_id == empresa_id))).scalar_one_or_none()
    if item is None:
        item = SuscripcionModel(empresa_id=empresa_id, plan_id=plan.id, estado=body.estado, fecha_fin=body.fecha_fin, creado_por_id=user.id); session.add(item)
    else: item.plan_id, item.estado, item.fecha_fin = plan.id, body.estado, body.fecha_fin
    await _sync_modules(session, empresa_id, plan.id); await session.flush()
    await _audit(session, user.id, "SUBSCRIPTION_MANUAL_ADJUSTMENT", "Suscripción ajustada por plataforma", item.id, empresa_id, {"plan_id": plan.id, "estado": item.estado})
    return await _subscription_payload(session, item)


@router.post("/checkout", response_model=RedirectResponse, summary="Crear Checkout", description="Crea una sesión Stripe Checkout en modo suscripción para el tenant.")
async def create_checkout(body: CheckoutRequest, user: CurrentUser = Depends(require_scoped_permission("suscripcion:contratar", "platform:suscripciones:gestionar")), session: AsyncSession = Depends(get_session)):
    if not user.empresa_id: raise HTTPException(403, "Solo una empresa puede contratar un plan")
    _stripe_ready(); plan = await session.get(PlanSuscripcionModel, body.plan_id)
    if not plan or not plan.activo or not plan.stripe_price_id: raise HTTPException(409, "El plan no está disponible para pagos")
    item = await _target_subscription(session, user.empresa_id); company = await session.get(EmpresaModel, user.empresa_id)
    if not item.stripe_customer_id:
        customer = await asyncio.to_thread(stripe.Customer.create, email=company.email, name=company.nombre_comercial, metadata={"empresa_id": company.id})
        item.stripe_customer_id = customer.id
    checkout = await asyncio.to_thread(stripe.checkout.Session.create, mode="subscription", customer=item.stripe_customer_id, line_items=[{"price": plan.stripe_price_id, "quantity": 1}], success_url=settings.stripe_checkout_success_url, cancel_url=settings.stripe_checkout_cancel_url, client_reference_id=user.empresa_id, metadata={"empresa_id": user.empresa_id, "plan_id": plan.id}, subscription_data={"metadata": {"empresa_id": user.empresa_id, "plan_id": plan.id}})
    item.stripe_checkout_session_id = checkout.id
    await _audit(session, user.id, "SUBSCRIPTION_CHECKOUT_CREATED", "Checkout de suscripción creado", item.id, user.empresa_id, {"plan_id": plan.id})
    return {"url": checkout.url}


@router.post("/portal", response_model=RedirectResponse, summary="Abrir portal de pagos", description="Crea una sesión temporal de Stripe Customer Portal.")
async def create_portal(user: CurrentUser = Depends(require_scoped_permission("suscripcion:gestionar_pago", "platform:suscripciones:gestionar")), session: AsyncSession = Depends(get_session)):
    if not user.empresa_id: raise HTTPException(403, "Solo una empresa puede abrir su portal")
    _stripe_ready(); item = await _target_subscription(session, user.empresa_id)
    if not item.stripe_customer_id: raise HTTPException(409, "La empresa todavía no tiene cliente Stripe")
    portal = await asyncio.to_thread(stripe.billing_portal.Session.create, customer=item.stripe_customer_id, return_url=settings.stripe_portal_return_url)
    return {"url": portal.url}


def _map_status(value: str) -> str:
    return {"active": "ACTIVA", "trialing": "PRUEBA", "past_due": "PAGO_FALLIDO", "unpaid": "PAGO_FALLIDO", "canceled": "CANCELADA", "incomplete": "PENDIENTE", "incomplete_expired": "VENCIDA", "paused": "SUSPENDIDA"}.get(value, "PENDIENTE")


@webhook_router.post("/stripe", summary="Recibir webhook Stripe", description="Verifica la firma y procesa eventos de suscripción de forma idempotente.")
async def stripe_webhook(request: Request, stripe_signature: str = Header(alias="Stripe-Signature"), session: AsyncSession = Depends(get_session)):
    _stripe_ready(webhook=True); payload = await request.body()
    try: event = stripe.Webhook.construct_event(payload, stripe_signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc: raise HTTPException(400, "Firma Stripe inválida") from exc
    if await session.scalar(select(StripeEventoModel.id).where(StripeEventoModel.stripe_event_id == event["id"])): return {"received": True, "duplicate": True}
    log = StripeEventoModel(stripe_event_id=event["id"], tipo=event["type"], estado_procesamiento="PROCESANDO"); session.add(log)
    obj = event["data"]["object"]; event_type = event["type"]
    try:
        item = None
        if event_type == "checkout.session.completed":
            empresa_id = obj.get("metadata", {}).get("empresa_id") or obj.get("client_reference_id")
            item = await _target_subscription(session, empresa_id); item.plan_id = obj["metadata"]["plan_id"]
            item.stripe_customer_id, item.stripe_subscription_id = obj.get("customer"), obj.get("subscription"); item.estado = "ACTIVA"
        elif event_type.startswith("customer.subscription."):
            item = (await session.execute(select(SuscripcionModel).where((SuscripcionModel.stripe_subscription_id == obj.get("id")) | (SuscripcionModel.stripe_customer_id == obj.get("customer"))))).scalar_one_or_none()
            if item: item.stripe_subscription_id = obj.get("id"); item.estado = _map_status(obj.get("status", "")); item.cancelar_al_fin_periodo = bool(obj.get("cancel_at_period_end")); item.fecha_proximo_cobro = datetime.fromtimestamp(obj["current_period_end"], UTC) if obj.get("current_period_end") else None
        elif event_type in {"invoice.paid", "invoice.payment_failed"}:
            item = (await session.execute(select(SuscripcionModel).where(SuscripcionModel.stripe_customer_id == obj.get("customer")))).scalar_one_or_none()
            if item: item.estado = "ACTIVA" if event_type == "invoice.paid" else "PAGO_FALLIDO"; item.fecha_ultimo_pago = datetime.now(UTC) if event_type == "invoice.paid" else item.fecha_ultimo_pago
        if item:
            await _sync_modules(session, item.empresa_id, item.plan_id)
            await _audit(session, None, "SUBSCRIPTION_UPDATED", f"Stripe procesó {event_type}", item.id, item.empresa_id, {"estado": item.estado})
        log.estado_procesamiento = "PROCESADO"; log.fecha_procesamiento = datetime.now(UTC)
    except Exception as exc:
        log.estado_procesamiento = "FALLIDO"; log.error = str(exc)[:2000]; log.fecha_procesamiento = datetime.now(UTC)
        await session.commit()
        raise
    return {"received": True}
