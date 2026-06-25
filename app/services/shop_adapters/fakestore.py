import httpx

from app.core.config import settings
from app.core.http_retry import get_with_retry
from app.core.logger import get_logger
from app.services.shop_adapters.base import BaseShopAdapter, ShopProduct

logger = get_logger(__name__)


class FakeStoreAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        logger.info(f"[START] FakeStoreAdapter.fetch_products | url={self.base_url}")

        async with httpx.AsyncClient(timeout=settings.shop_api_timeout) as client:
            resp = await get_with_retry(
                client,
                f"{self.base_url}/products",
                attempts=settings.shop_api_retry_attempts,
            )

        products = [
            ShopProduct(
                external_id=str(p["id"]),
                title=p["title"],
                description=p.get("description", ""),
                category=p.get("category", ""),
                price_usd=float(p["price"]),
            )
            for p in resp.json()
        ]

        logger.info(f"[OK]    FakeStoreAdapter.fetch_products | total={len(products)}")
        return products
