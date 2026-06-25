from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import func, select

from app.api import router as api_router
from app.core.config import settings
from app.core.logger import get_logger, log_operation, setup_logging
from app.core.redis import redis_client
from app.db.models.product import Product
from app.db.models.shop import Shop
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.services.currency_service import CurrencyService
from app.services.db_service import db_service
from app.tasks.seed import seed_demo_user, seed_products, seed_shops

setup_logging()

logger = get_logger(__name__)


async def run_seed_if_needed() -> None:
    with log_operation(logger, "startup seed"):
        async with db_service.create_session(readonly=False) as db:
            await seed_demo_user(db)

            # Каждый шаг проверяем независимо — защита от частично выполненного seed
            shops_result = await db.execute(select(Shop))
            shops = shops_result.scalars().all()

            if not shops:
                logger.info("No shops found — running seed_shops")
                shop_ids = await seed_shops(db)
            else:
                shop_ids = {s.adapter_key: s.id for s in shops}
                logger.info(f"Shops already exist: {list(shop_ids.keys())}")

            products_count = (await db.execute(select(func.count(Product.id)))).scalar()
            if products_count == 0:
                logger.info("No products found — running seed_products")
                try:
                    await seed_products(db, shop_ids)
                except Exception as e:
                    logger.warning(f"Could not seed products (API unavailable?): {e}")
            else:
                logger.info(f"Products already exist ({products_count}), skipping")

            # Курсы синхронизируем при каждом старте (идемпотентный upsert на сегодня),
            # чтобы /currencies всегда отдавал актуальные значения, не дожидаясь beat.
            try:
                currency_service = CurrencyService(ExchangeRateRepo(db), redis_client)
                synced = await currency_service.sync_today_rates()
                await db.commit()
                logger.info(f"Synced {synced} exchange rates for today")
            except Exception as e:
                logger.warning(f"Could not sync exchange rates (NBU unavailable?): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────
    logger.info("Application startup")
    if settings.run_seed_on_startup:
        await run_seed_if_needed()
    yield
    # ── SHUTDOWN ─────────────────────────────────────────────
    logger.info("Application shutdown — disposing DB engine")
    await db_service.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Price Tracker API",
    description="Service for tracking product prices across multiple shops",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router)
