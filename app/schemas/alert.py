import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import Currency


class AlertCreate(BaseModel):
    product_id: uuid.UUID
    threshold_price: Decimal = Field(gt=0, description="Порог в указанной валюте")
    currency: Currency = Currency.USD

    model_config = ConfigDict(extra="forbid")


class AlertResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    threshold_price_usd: Decimal | None
    currency_code: Currency | None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AlertListResponse(BaseModel):
    items: list[AlertResponse]
