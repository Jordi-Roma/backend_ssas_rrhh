from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ssas.suscripciones.application.features import PlanFeature
from ssas.suscripciones.application.policy import has_plan_feature


async def require_plan_feature(
    session: AsyncSession, empresa_id: str, feature: PlanFeature
) -> None:
    if not await has_plan_feature(session, empresa_id, feature):
        raise HTTPException(403, "Esta función no está incluida en el plan de la empresa")
