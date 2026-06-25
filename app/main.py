from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import router as api_router
from app.api.errors import register_exception_handlers
from app.core.config import settings
from app.core.logger import get_logger, setup_logging
from app.services.db_service import db_service
from app.tasks.seed import run_seed_if_needed

setup_logging()

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup")
    if settings.run_seed_on_startup:
        await run_seed_if_needed()
    yield
    logger.info("Application shutdown — disposing DB engine")
    await db_service.dispose()
    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Price Tracker API",
        description="Service for tracking product prices across multiple shops",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()