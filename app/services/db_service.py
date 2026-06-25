from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


class DatabaseService:
    def __init__(self) -> None:
        self.engine = create_async_engine(
            str(settings.database_url),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=3600,
        )
        self._session_factory = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    @staticmethod
    def _abort_ro(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Write operation attempted on a read-only session")

    def create_session(self, readonly: bool = True) -> AsyncSession:
        session = self._session_factory()
        if readonly:
            session.flush = DatabaseService._abort_ro  # type: ignore[method-assign]
            session.commit = DatabaseService._abort_ro  # type: ignore[method-assign]
        return session

    @asynccontextmanager
    async def create_session_if_missing(
        self,
        readonly: bool = True,
        db_session: AsyncSession | None = None,
    ) -> AsyncGenerator[tuple[bool, AsyncSession], None]:
        if db_session is None:
            async with self.create_session(readonly=readonly) as session:
                yield False, session
        else:
            yield True, db_session

    async def dispose(self) -> None:
        await self.engine.dispose()


db_service = DatabaseService()
