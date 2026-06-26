import asyncio

from app.core.logger import get_logger
from app.core.redis import create_redis_client
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.services.currency_service import CurrencyService
from app.services.db_service import begin_task_session
from app.tasks.celery_app import app

logger = get_logger(__name__)


@app.task(name="tasks.sync_exchange_rates")
def sync_exchange_rates_task() -> int:
    """Load current currency rates from NBU into the DB every day."""
    logger.info("[TASK] sync_exchange_rates_task started")
    synced = asyncio.run(_sync_today_async())
    logger.info(f"[TASK] sync_exchange_rates_task finished | synced={synced}")
    return synced


async def _sync_today_async() -> int:
    redis = create_redis_client()
    try:
        async with begin_task_session() as db:
            service = CurrencyService(ExchangeRateRepo(db), redis)
            synced = await service.sync_today_rates()
            await db.commit()
            return synced
    finally:
        await redis.aclose()
