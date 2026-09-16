from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.auth.infrastructure.persistence.models.user import UserModel
from ssas.empresas.infrastructure.persistence.models.suscripcion import (
    PlanSuscripcionModel,
    SuscripcionModel,
)
from ssas.postulantes.infrastructure.persistence.models.postulante import PostulanteModel
from ssas.vacantes.infrastructure.persistence.models.vacante import VacanteModel


class SubscriptionPolicyError(RuntimeError):
    pass


class SubscriptionPolicy:
    def __init__(self, session: AsyncSession, grace_days: int = 3):
        self.session = session
        self.grace_days = grace_days

    async def current(self, empresa_id: str) -> tuple[SuscripcionModel, PlanSuscripcionModel]:
        result = await self.session.execute(
            select(SuscripcionModel, PlanSuscripcionModel)
            .join(PlanSuscripcionModel, PlanSuscripcionModel.id == SuscripcionModel.plan_id)
            .where(SuscripcionModel.empresa_id == empresa_id)
        )
        row = result.first()
        if row is None:
            raise SubscriptionPolicyError("La empresa no tiene una suscripción asignada")
        return row[0], row[1]

    async def require_operational(self, empresa_id: str) -> PlanSuscripcionModel:
        subscription, plan = await self.current(empresa_id)
        allowed = subscription.estado in {"ACTIVA", "PRUEBA"}
        if subscription.estado == "PAGO_FALLIDO":
            allowed = subscription.updated_at + timedelta(days=self.grace_days) >= datetime.now(UTC)
        if not allowed:
            raise SubscriptionPolicyError(
                f"La suscripción está {subscription.estado.lower()}; regulariza el plan para continuar"
            )
        return plan

    async def require_user_capacity(self, empresa_id: str) -> None:
        plan = await self.require_operational(empresa_id)
        count = await self.session.scalar(
            select(func.count(UserModel.id)).where(
                UserModel.empresa_id == empresa_id,
                UserModel.is_active.is_(True),
                UserModel.eliminado_at.is_(None),
            )
        )
        if (count or 0) >= plan.max_usuarios:
            raise SubscriptionPolicyError(f"El plan permite como máximo {plan.max_usuarios} usuarios activos")

    async def require_vacancy_capacity(self, empresa_id: str) -> None:
        plan = await self.require_operational(empresa_id)
        count = await self.session.scalar(
            select(func.count(VacanteModel.id)).where(
                VacanteModel.empresa_id == empresa_id,
                VacanteModel.estado == "PUBLICADA",
            )
        )
        if (count or 0) >= plan.max_vacantes_activas:
            raise SubscriptionPolicyError(
                f"El plan permite como máximo {plan.max_vacantes_activas} vacantes activas"
            )

    async def require_storage(self, empresa_id: str, bytes_to_add: int, directory: str = "uploads/cv") -> None:
        plan = await self.require_operational(empresa_id)
        used = await self._storage_used(empresa_id, directory)
        limit = plan.max_almacenamiento_mb * 1024 * 1024
        if used + bytes_to_add > limit:
            raise SubscriptionPolicyError(
                f"El plan permite como máximo {plan.max_almacenamiento_mb} MB de almacenamiento"
            )

    async def consumption(self, empresa_id: str) -> dict:
        subscription, plan = await self.current(empresa_id)
        users = await self.session.scalar(select(func.count(UserModel.id)).where(UserModel.empresa_id == empresa_id, UserModel.is_active.is_(True), UserModel.eliminado_at.is_(None)))
        vacancies = await self.session.scalar(select(func.count(VacanteModel.id)).where(VacanteModel.empresa_id == empresa_id, VacanteModel.estado == "PUBLICADA"))
        storage_bytes = await self._storage_used(empresa_id)
        return {
            "estado": subscription.estado,
            "usuarios": {"usado": users or 0, "limite": plan.max_usuarios},
            "vacantes_activas": {"usado": vacancies or 0, "limite": plan.max_vacantes_activas},
            "almacenamiento_mb": {"usado": round(storage_bytes / 1024 / 1024, 2), "limite": plan.max_almacenamiento_mb},
        }

    async def _storage_used(self, empresa_id: str, directory: str = "uploads/cv") -> int:
        result = await self.session.execute(
            select(PostulanteModel.cv_url).where(
                PostulanteModel.empresa_id == empresa_id,
                PostulanteModel.cv_url.is_not(None),
            )
        )
        base = Path(directory).resolve()
        total = 0
        for stored in result.scalars().all():
            candidate = (base / Path(stored).name).resolve()
            if candidate.is_relative_to(base) and candidate.is_file():
                total += candidate.stat().st_size
        return total
