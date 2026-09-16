import asyncio

from ssas.config.settings import settings
from ssas.infrastructure.database.session import AsyncSessionLocal, dispose_engine
from ssas.suscripciones.application.reconciliation import reconcile_subscriptions


async def main() -> None:
    try:
        async with AsyncSessionLocal() as session:
            changed = await reconcile_subscriptions(session, settings.subscription_grace_days)
            await session.commit()
            print(f"Suscripciones reconciliadas: {changed}")
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
