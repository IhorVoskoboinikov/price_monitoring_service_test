from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, PriceServiceDep
from app.schemas.enums import Currency
from app.schemas.product import CatalogResponse

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("", response_model=CatalogResponse)
async def get_catalog(
    _: CurrentUser,
    service: PriceServiceDep,
    currency: Currency = Query(Currency.USD),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> CatalogResponse:
    """Browse the whole product catalog (to find product_id for the watchlist)."""
    return await service.get_catalog(currency, page, page_size)
