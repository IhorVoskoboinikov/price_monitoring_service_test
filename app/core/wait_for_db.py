import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.logger import get_logger, setup_logging

logger = get_logger(__name__)


async def wait_for_db(retries: int = 10, delay: int = 3) -> None:
    engine = create_async_engine(str(settings.database_url))
    logger.info(f"[START] wait_for_db | retries={retries} delay={delay}s")

    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("[OK]    wait_for_db | database is ready")
            await engine.dispose()
            return
        except Exception as e:
            logger.warning(f"[WAIT]  wait_for_db | attempt={attempt}/{retries} | {e}")
            if attempt == retries:
                logger.error("[FAIL]  wait_for_db | database unavailable after all retries — exiting")
                sys.exit(1)
            await asyncio.sleep(delay)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(wait_for_db())
