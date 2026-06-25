import asyncio
from datetime import date

from sqlalchemy import text

from app.core.logger import get_logger, log_operation
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.shop_repo import ShopRepo
from app.services.db_service import begin_task_session
from app.services.price_fetcher import PriceFetcherService
from app.tasks.celery_app import app

logger = get_logger(__name__)


@app.task(name="tasks.fetch_prices")
def fetch_prices_task() -> dict[str, int]:
    """Fetch current prices from all active shops and write to price_history."""
    logger.info("[TASK] fetch_prices_task started")
    result = asyncio.run(_fetch_prices_async())
    logger.info(f"[TASK] fetch_prices_task finished | result={result}")
    return result


async def _fetch_prices_async() -> dict[str, int]:
    async with begin_task_session() as db:
        service = PriceFetcherService(ShopRepo(db), PriceRepo(db))
        results = await service.fetch_all()
        await db.commit()
        return results


@app.task(name="tasks.create_price_history_partition")
def create_price_history_partition_task() -> str:
    """Create next month's price_history partition if it doesn't exist."""
    logger.info("[TASK] create_price_history_partition_task started")
    result = asyncio.run(_create_partition_async())
    logger.info(
        f"[TASK] create_price_history_partition_task finished | partition={result}"
    )
    return result


async def _create_partition_async() -> str:
    today = date.today()

    # Calculate next month boundaries
    if today.month == 12:
        next_start = date(today.year + 1, 1, 1)
        next_end = date(today.year + 1, 2, 1)
    else:
        next_start = date(today.year, today.month + 1, 1)
        if today.month + 1 == 12:
            next_end = date(today.year + 1, 1, 1)
        else:
            next_end = date(today.year, today.month + 2, 1)

    partition_name = f"price_history_{next_start.year}_{next_start.month:02d}"

    with log_operation(
        logger, "create_price_history_partition", partition=partition_name
    ):
        async with begin_task_session() as db:
            await db.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name} "
                    f"PARTITION OF price_history "
                    f"FOR VALUES FROM ('{next_start}') TO ('{next_end}')"
                )
            )
            await db.commit()

    return partition_name
