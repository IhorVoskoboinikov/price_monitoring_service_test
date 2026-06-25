import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import redis_client
from app.core.security import verify_token
from app.db.repositories.alert_repo import AlertRepo
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.product_repo import ProductRepo
from app.db.repositories.user_product_repo import UserProductRepo
from app.services.alert_service import AlertService
from app.services.currency_service import CurrencyService
from app.services.db_service import db_service
from app.services.price_service import PriceService
from app.services.user_product_service import UserProductService

# ── Auth ─────────────────────────────────────────────────────────────────────

CurrentUser = Annotated[dict, Depends(verify_token)]


def get_current_user_id(user: CurrentUser) -> uuid.UUID:
    """Extract user_id UUID from the JWT payload."""
    raw = user.get("user_id")
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain user_id",
        )
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token user_id is not a valid UUID",
        )


CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]

# ── Database session ─────────────────────────────────────────────────────────


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    """Сессия на запрос. Транзакция управляется здесь: commit при успехе,
    rollback при любой ошибке. Сервисы и репозитории не коммитят сами."""
    async with db_service.session() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


DbSession = Annotated[AsyncSession, Depends(_get_db)]

# ── Service providers (DI) ───────────────────────────────────────────────────


def get_currency_service(db: DbSession) -> CurrencyService:
    return CurrencyService(ExchangeRateRepo(db), redis_client)


CurrencyServiceDep = Annotated[CurrencyService, Depends(get_currency_service)]


def get_price_service(
    db: DbSession, currency: CurrencyServiceDep
) -> PriceService:
    return PriceService(ProductRepo(db), PriceRepo(db), currency)


PriceServiceDep = Annotated[PriceService, Depends(get_price_service)]


def get_alert_service(
    db: DbSession, currency: CurrencyServiceDep
) -> AlertService:
    return AlertService(AlertRepo(db), ProductRepo(db), currency)


AlertServiceDep = Annotated[AlertService, Depends(get_alert_service)]


def get_user_product_service(
    db: DbSession, price_service: PriceServiceDep
) -> UserProductService:
    return UserProductService(UserProductRepo(db), ProductRepo(db), price_service)


UserProductServiceDep = Annotated[UserProductService, Depends(get_user_product_service)]
