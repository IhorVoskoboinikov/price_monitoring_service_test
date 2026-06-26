"""
Manually run the price-alert check (without waiting for Celery Beat).

Usage (inside the api container, project mounted at /app):
    docker compose exec -e PYTHONPATH=/app api python scripts/run_check_alerts.py
"""

import asyncio

from app.core.logger import setup_logging
from app.tasks.alerts import _check_alerts_async

if __name__ == "__main__":
    setup_logging()  # turn on INFO logs (including console-mode email)
    sent = asyncio.run(_check_alerts_async())
    print(f"Alerts triggered & emailed: {sent}")
