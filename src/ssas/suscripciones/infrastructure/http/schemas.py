from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    descripcion: str | None = Field(default=None, max_length=1000)
    precio_mensual: Decimal = Field(ge=0)
    moneda: str = Field(default="USD", min_length=3, max_length=3)
    max_usuarios: int = Field(ge=1, le=100000)
    max_vacantes_activas: int = Field(ge=1, le=100000)
    max_almacenamiento_mb: int = Field(ge=1, le=1000000)
    stripe_price_id: str | None = Field(default=None, max_length=120)
    modulos: list[str] = Field(default_factory=list)
    activo: bool = True


class PlanResponse(PlanRequest):
    id: str


class SubscriptionResponse(BaseModel):
    id: str
    empresa_id: str
    plan: PlanResponse
    estado: str
    fecha_inicio: date
    fecha_fin: date | None
    periodo_prueba_hasta: date | None
    cancelar_al_fin_periodo: bool
    fecha_ultimo_pago: datetime | None
    fecha_proximo_cobro: datetime | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None


class AssignSubscriptionRequest(BaseModel):
    plan_id: str
    estado: Literal[
        "PRUEBA",
        "PENDIENTE",
        "ACTIVA",
        "VENCIDA",
        "PAGO_FALLIDO",
        "SUSPENDIDA",
        "CANCELADA",
    ] = "ACTIVA"
    fecha_fin: date | None = None


class CheckoutRequest(BaseModel):
    plan_id: str


class RedirectResponse(BaseModel):
    url: str


class LimitUsage(BaseModel):
    usado: float
    limite: float


class ConsumptionResponse(BaseModel):
    estado: str
    usuarios: LimitUsage
    vacantes_activas: LimitUsage
    almacenamiento_mb: LimitUsage
