import httpx

from app.core.config import settings
from app.core.http_retry import get_with_retry
from app.core.logger import get_logger
from app.services.shop_adapters.base import BaseShopAdapter, ShopProduct

logger = get_logger(__name__)


class DummyJsonAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        products: list[ShopProduct] = []
        skip, limit = 0, 100

        logger.info(f"[START] DummyJsonAdapter.fetch_products | url={self.base_url}")

        async with httpx.AsyncClient(timeout=settings.shop_api_timeout) as client:
            while True:
                resp = await get_with_retry(
                    client,
                    f"{self.base_url}/products?limit={limit}&skip={skip}",
                    attempts=settings.shop_api_retry_attempts,
                )

                data = resp.json()
                page_count = len(data["products"])
                logger.debug(
                    f"Page received | skip={skip} count={page_count} "
                    f"total={data['total']}"
                )

                for p in data["products"]:
                    products.append(
                        ShopProduct(
                            external_id=str(p["id"]),
                            title=p["title"],
                            description=p.get("description", ""),
                            category=p.get("category", ""),
                            price_usd=float(p["price"]),
                        )
                    )

                skip += limit
                if skip >= data["total"]:
                    break

        logger.info(f"[OK]    DummyJsonAdapter.fetch_products | total={len(products)}")
        return products
