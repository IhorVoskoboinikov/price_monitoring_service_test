from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.enums import Currency


class ShopPriceItem(BaseModel):
    shop_name: str
    price: Decimal
    currency: Currency
    last_updated: datetime


class PriceHistoryPoint(BaseModel):
    date: date
    price: Decimal


class PriceHistorySeries(BaseModel):
    shop_name: str
    data: list[PriceHistoryPoint]


class PriceHistoryResponse(BaseModel):
    series: list[PriceHistorySeries]
    average: list[PriceHistoryPoint]
