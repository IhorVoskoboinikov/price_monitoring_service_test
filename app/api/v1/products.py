import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, CurrentUserId, PriceServiceDep
from app.api.responses import NOT_FOUND
from app.schemas.enums import Currency, SortOption
from app.schemas.price import PriceHistoryResponse, ShopPriceItem
from app.schemas.product import ProductDetail, ProductListResponse

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
async def get_products(
    user_id: CurrentUserId,
    service: PriceServiceDep,
    currency: Currency = Query(Currency.USD),
    sort: SortOption = Query(SortOption.PRICE_ASC),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> ProductListResponse:
    return await service.get_products_list(user_id, currency, page, page_size, sort)


@router.get("/{product_id}", response_model=ProductDetail, responses=NOT_FOUND)
async def get_product(
    product_id: uuid.UUID,
    _: CurrentUser,
    service: PriceServiceDep,
    currency: Currency = Query(Currency.USD),
) -> ProductDetail:
    return await service.get_product_detail(product_id, currency)


@router.get(
    "/{product_id}/prices",
    response_model=list[ShopPriceItem],
    responses=NOT_FOUND,
)
async def get_product_prices(
    product_id: uuid.UUID,
    _: CurrentUser,
    service: PriceServiceDep,
    currency: Currency = Query(Currency.USD),
) -> list[ShopPriceItem]:
    return await service.get_current_prices(product_id, currency)


@router.get("/{product_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(
    product_id: uuid.UUID,
    _: CurrentUser,
    service: PriceServiceDep,
    currency: Currency = Query(Currency.USD),
    date_from: date = Query(default_factory=lambda: date.today() - timedelta(days=30)),
    date_to: date = Query(default_factory=date.today),
) -> PriceHistoryResponse:
    return await service.get_price_history(product_id, currency, date_from, date_to)
