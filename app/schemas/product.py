import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Currency, TrendDirection
from app.schemas.types import Money


class ProductListItem(BaseModel):
    id: uuid.UUID
    title: str
    category: str | None
    price_min: Money | None
    price_max: Money | None
    currency: Currency
    trend: TrendDirection

    model_config = ConfigDict(from_attributes=True)


class ProductListResponse(BaseModel):
    items: list[ProductListItem]
    page: int = Field(examples=[1])
    page_size: int = Field(examples=[20])
    total: int = Field(examples=[42])


class ProductDetail(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    category: str | None
    price_min: Money | None
    price_max: Money | None
    currency: Currency
    shops_count: int

    model_config = ConfigDict(from_attributes=True)


class CatalogItem(BaseModel):
    """One product in the global catalog (lean — no description)."""

    id: uuid.UUID
    title: str
    category: str | None
    price_min: Money | None
    price_max: Money | None
    currency: Currency
    shops_count: int

    model_config = ConfigDict(from_attributes=True)


class CatalogResponse(BaseModel):
    items: list[CatalogItem]
    page: int = Field(examples=[1])
    page_size: int = Field(examples=[20])
    total: int = Field(examples=[42])


class AddProductRequest(BaseModel):
    product_id: uuid.UUID


class WatchlistItem(BaseModel):
    """Response for adding a product to the watchlist."""

    product_id: uuid.UUID
