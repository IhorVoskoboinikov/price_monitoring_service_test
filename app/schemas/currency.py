from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CurrencyRateItem(BaseModel):
    currency_code: str
    rate_uah_per_unit: Decimal
    date: date

    model_config = ConfigDict(from_attributes=True)


class CurrenciesResponse(BaseModel):
    items: list[CurrencyRateItem]
