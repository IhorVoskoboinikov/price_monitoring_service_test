import asyncio

from app.core.logger import get_logger
from app.core.redis import create_redis_client
from app.db.repositories.alert_repo import AlertRepo
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.db.repositories.product_repo import ProductRepo
from app.services.alert_service import AlertService
from app.services.currency_service import CurrencyService
from app.services.db_service import begin_task_session
from app.tasks.celery_app import app

logger = get_logger(__name__)


@app.task(name="tasks.check_price_alerts")
def check_price_alerts_task() -> int:
    """Check active alerts and send email when a price drops below the threshold."""
    logger.info("[TASK] check_price_alerts_task started")
    sent = asyncio.run(_check_alerts_async())
    logger.info(f"[TASK] check_price_alerts_task finished | sent={sent}")
    return sent


async def _check_alerts_async() -> int:
    redis = create_redis_client()
    try:
        async with begin_task_session() as db:
            currency = CurrencyService(ExchangeRateRepo(db), redis)
            service = AlertService(AlertRepo(db), ProductRepo(db), currency)
            sent = await service.check_alerts()
            await db.commit()
            return sent
    finally:
        await redis.aclose()
