import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUserId, UserProductServiceDep
from app.api.responses import CONFLICT, NOT_FOUND
from app.schemas.enums import Currency
from app.schemas.product import AddProductRequest, ProductDetail, WatchlistItem

router = APIRouter(prefix="/me/products", tags=["me"])


@router.get("", response_model=list[ProductDetail])
async def get_user_products(
    user_id: CurrentUserId,
    service: UserProductServiceDep,
    currency: Currency = Query(Currency.USD),
) -> list[ProductDetail]:
    """List products the current user is tracking."""
    return await service.list_tracked(user_id, currency)


@router.post(
    "",
    response_model=WatchlistItem,
    status_code=201,
    responses={**NOT_FOUND, **CONFLICT},
)
async def add_user_product(
    body: AddProductRequest,
    user_id: CurrentUserId,
    service: UserProductServiceDep,
) -> WatchlistItem:
    """Add a product to the current user's watchlist."""
    await service.add(user_id, body.product_id)
    return WatchlistItem(product_id=body.product_id)


@router.delete("/{product_id}", status_code=204, responses=NOT_FOUND)
async def remove_user_product(
    product_id: uuid.UUID,
    user_id: CurrentUserId,
    service: UserProductServiceDep,
) -> None:
    """Remove a product from the current user's watchlist."""
    await service.remove(user_id, product_id)
