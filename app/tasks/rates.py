import asyncio

from app.core.logger import get_logger
from app.core.redis import redis_client
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.services.currency_service import CurrencyService
from app.services.db_service import db_service
from app.tasks.celery_app import app

logger = get_logger(__name__)


@app.task(name="tasks.sync_exchange_rates")
def sync_exchange_rates_task() -> int:
    """Ежедневно загружает текущие курсы валют с НБУ в БД."""
    logger.info("[TASK] sync_exchange_rates_task started")
    synced = asyncio.run(_sync_today_async())
    logger.info(f"[TASK] sync_exchange_rates_task finished | synced={synced}")
    return synced


async def _sync_today_async() -> int:
    async with db_service.create_session(readonly=False) as db:
        service = CurrencyService(ExchangeRateRepo(db), redis_client)
        synced = await service.sync_today_rates()
        await db.commit()
        return synced
