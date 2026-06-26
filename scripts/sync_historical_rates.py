"""
On-demand load of historical currency rates from NBU.

Usage (inside the api container, project mounted at /app):
    docker compose exec -e PYTHONPATH=/app api \
        python scripts/sync_historical_rates.py [DAYS]

DAYS — how many days back to load (default 30).
Loads day by day for USD/EUR/GBP, idempotent (dates already present are skipped).
"""

import asyncio
import sys
from datetime import date, timedelta

from app.core.logger import setup_logging
from app.core.redis import redis_client
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.services.currency_service import CurrencyService
from app.services.db_service import db_service


async def _run(days: int) -> int:
    today = date.today()
    date_from = today - timedelta(days=days)
    async with db_service.session() as db:
        service = CurrencyService(ExchangeRateRepo(db), redis_client)
        written = await service.sync_historical_rates(date_from, today)
        await db.commit()
        return written


if __name__ == "__main__":
    setup_logging()
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    written = asyncio.run(_run(days))
    print(f"Historical rates written: {written} (last {days} days)")
