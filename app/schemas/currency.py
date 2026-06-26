from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CurrencyRateItem(BaseModel):
    currency_code: str = Field(examples=["USD"])
    rate_uah_per_unit: Decimal = Field(examples=["41.50"])
    date: date

    model_config = ConfigDict(from_attributes=True)


class CurrenciesResponse(BaseModel):
    items: list[CurrencyRateItem]
