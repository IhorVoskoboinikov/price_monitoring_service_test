from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


class DatabaseService:
    """Общий engine приложения.

    FastAPI работает в одном event loop (uvicorn), поэтому переиспользует общий
    пул соединений через `session()`. Для Celery-задач, где `asyncio.run()`
    создаёт новый event loop на каждый вызов, общий engine использовать нельзя
    (asyncpg-соединения привязаны к loop'у) — там применяется `begin_task_session()`.
    """

    def __init__(self) -> None:
        self.engine = create_async_engine(
            str(settings.database_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
        self._session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Сессия на общем engine приложения (один event loop)."""
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


db_service = DatabaseService()


@asynccontextmanager
async def begin_task_session() -> AsyncGenerator[AsyncSession, None]:
    """Сессия с собственным engine на текущий event loop — для Celery-задач.

    Каждый запуск задачи идёт через `asyncio.run()` (новый loop), поэтому
    поднимаем изолированный engine и гарантированно закрываем его в конце,
    чтобы не переиспользовать соединения из чужого/закрытого loop'а.
    """
    engine = create_async_engine(str(settings.database_url), pool_pre_ping=True)
    try:
        factory = async_sessionmaker(
            engine, expire_on_commit=False, autoflush=False
        )
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()
