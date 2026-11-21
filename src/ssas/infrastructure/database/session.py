import asyncio
import sys
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ssas.config.settings import settings
from ssas.infrastructure.database.base import import_all_models

import_all_models()

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_recycle=settings.db_pool_recycle_seconds,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Entrega una transacción por petición y revierte automáticamente ante errores."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
            pending = session.info.pop("notifications_to_push", [])
            if pending:
                from ssas.personal.push_service import send_pending_push
                await send_pending_push(session, pending)
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Libera el pool al cerrar la aplicación o al finalizar pruebas."""
    await engine.dispose()
