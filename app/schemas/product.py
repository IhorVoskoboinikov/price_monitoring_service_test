import uuid
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.enums import Currency, TrendDirection


class ProductListItem(BaseModel):
    id: uuid.UUID
    title: str
    category: Optional[str]
    price_min: Optional[Decimal]
    price_max: Optional[Decimal]
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
    description: Optional[str]
    category: Optional[str]
    price_min: Optional[Decimal]
    price_max: Optional[Decimal]
    currency: Currency
    shops_count: int

    model_config = ConfigDict(from_attributes=True)


class AddProductRequest(BaseModel):
    product_id: uuid.UUID


class WatchlistItem(BaseModel):
    """Ответ на добавление товара в watchlist."""

    product_id: uuid.UUID
