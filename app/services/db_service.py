from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


class DatabaseService:
    """Shared application engine.

    FastAPI runs in a single event loop (uvicorn), so it reuses one shared
    connection pool through `session()`. For Celery tasks, where `asyncio.run()`
    makes a new event loop on each call, the shared engine cannot be used
    (asyncpg connections are bound to a loop) — there we use `begin_task_session()`.
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
        """A session on the shared app engine (one event loop)."""
        async with self._session_factory() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


db_service = DatabaseService()


@asynccontextmanager
async def begin_task_session() -> AsyncGenerator[AsyncSession, None]:
    """A session with its own engine on the current event loop — for Celery tasks.

    Each task run goes through `asyncio.run()` (a new loop), so we create an
    isolated engine and always close it at the end, to avoid reusing connections
    from another/closed loop.
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
