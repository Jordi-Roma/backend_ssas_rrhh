"""Comando de Railway Cron: revisa copias vencidas como respaldo del worker."""

import asyncio

from ssas.infrastructure.database.session import dispose_engine
from ssas.respaldos.infrastructure.services.tenant_jobs import schedule_daily_backups


async def main() -> None:
    try:
        await schedule_daily_backups()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
