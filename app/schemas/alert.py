import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Currency
from app.schemas.types import Money


class AlertCreate(BaseModel):
    product_id: uuid.UUID
    threshold_price: Decimal = Field(
        gt=0, examples=["12.99"], description="Threshold in chosen currency"
    )
    currency: Currency = Currency.USD

    model_config = ConfigDict(extra="forbid")


class AlertResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    threshold_price_usd: Money | None
    currency_code: Currency | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
