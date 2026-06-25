from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

app = Celery("price_tracker")

app.conf.update(
    broker_url=str(settings.celery_broker_url),
    result_backend=str(settings.celery_result_backend),
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    include=["app.tasks.prices", "app.tasks.alerts", "app.tasks.rates"],
)

app.conf.beat_schedule = {
    "fetch-prices": {
        "task": "tasks.fetch_prices",
        # каждые FETCH_PRICES_INTERVAL_HOURS часов (из .env, по умолчанию 4)
        "schedule": settings.fetch_prices_interval_hours * 3600,
    },
    "check-price-alerts": {
        "task": "tasks.check_price_alerts",
        "schedule": settings.check_alerts_interval_minutes * 60,
    },
    "sync-exchange-rates": {
        "task": "tasks.sync_exchange_rates",
        # ежедневно в SYNC_RATES_CRON_HOUR:00 UTC
        "schedule": crontab(hour=settings.sync_rates_cron_hour, minute=0),
    },
    "create-price-history-partition-monthly": {
        "task": "tasks.create_price_history_partition",
        # 1-го числа каждого месяца в 00:05
        "schedule": crontab(day_of_month=1, hour=0, minute=5),
    },
}
