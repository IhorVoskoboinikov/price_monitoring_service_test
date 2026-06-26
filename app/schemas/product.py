import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import Currency, TrendDirection


class ProductListItem(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: Currency
    trend: TrendDirection

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    items: list[ProductListItem]
    page: int
    page_size: int
    total: int


class ProductDetail(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    category: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: Currency
    shops_count: int

    model_config = ConfigDict(from_attributes=True)


class AddProductRequest(BaseModel):
    product_id: uuid.UUID


class WatchlistItem(BaseModel):
    """Response for adding a product to the watchlist."""

    product_id: uuid.UUID
