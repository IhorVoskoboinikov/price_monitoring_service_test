from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Base repository: holds the session passed in the constructor.

    The repository does not manage the session lifecycle and does not commit —
    that is the job of the calling layer (service/endpoint/task) that owns the
    transaction. This keeps repositories reusable in both HTTP requests and
    Celery tasks.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def flush(self) -> None:
        """Flush changes to the DB without committing (for server-default fields)."""
        await self.db.flush()

    async def refresh(self, obj: object) -> None:
        """Re-read the object from the DB (for example, to get created_at)."""
        await self.db.refresh(obj)
