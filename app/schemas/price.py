from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.enums import Currency
from app.schemas.types import Money


class ShopPriceItem(BaseModel):
    shop_name: str
    price: Money
    currency: Currency
    last_updated: datetime


class PriceHistoryPoint(BaseModel):
    date: date
    price: Money


class PriceHistorySeries(BaseModel):
    shop_name: str
    data: list[PriceHistoryPoint]


class PriceHistoryResponse(BaseModel):
    series: list[PriceHistorySeries]
    average: list[PriceHistoryPoint]
