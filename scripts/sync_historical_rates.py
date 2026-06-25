"""
On-demand загрузка исторических курсов валют с НБУ.

Usage (внутри контейнера api, проект смонтирован в /app):
    docker compose exec -e PYTHONPATH=/app api \
        python scripts/sync_historical_rates.py [DAYS]

DAYS — сколько дней назад грузить (по умолчанию 30).
Грузит по дням для USD/EUR/GBP, идемпотентно (уже имеющиеся даты пропускаются).
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
    async with db_service.create_session(readonly=False) as db:
        service = CurrencyService(ExchangeRateRepo(db), redis_client)
        written = await service.sync_historical_rates(date_from, today)
        await db.commit()
        return written


if __name__ == "__main__":
    setup_logging()
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    written = asyncio.run(_run(days))
    print(f"Historical rates written: {written} (last {days} days)")
