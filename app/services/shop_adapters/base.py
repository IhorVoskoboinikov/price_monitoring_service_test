from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ShopProduct:
    external_id: str
    title: str
    description: str
    category: str
    price_usd: Decimal


class BaseShopAdapter(ABC):
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    @abstractmethod
    async def fetch_products(self) -> list[ShopProduct]: ...
