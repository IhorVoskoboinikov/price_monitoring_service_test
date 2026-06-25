from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Базовый репозиторий: держит сессию, переданную через конструктор.

    Репозиторий не управляет жизненным циклом сессии и не коммитит — это
    ответственность вызывающего слоя (сервиса/эндпоинта/задачи), который владеет
    транзакцией. Так репозитории остаются переиспользуемыми и в HTTP-запросах,
    и в Celery-задачах.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def flush(self) -> None:
        """Сбросить изменения в БД, не коммитя транзакцию (для server-default полей)."""
        await self.db.flush()

    async def refresh(self, obj: object) -> None:
        """Перечитать объект из БД (например, чтобы получить created_at)."""
        await self.db.refresh(obj)
