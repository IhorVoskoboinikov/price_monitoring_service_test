from datetime import datetime, timedelta, timezone

from app.core.logger import get_logger, log_operation
from app.db.models.shop import Shop
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.shop_repo import ShopRepo
from app.services.shop_adapters.registry import get_adapter

logger = get_logger(__name__)

# Do not write a repeated price snapshot if one was already made within this window.
_DEDUP_WINDOW = timedelta(hours=1)


class PriceFetcherService:
    def __init__(self, shops: ShopRepo, prices: PriceRepo) -> None:
        self.shops = shops
        self.prices = prices

    async def fetch_all(self) -> dict[str, int]:
        """Take current prices from all active shops.

        Returns {adapter_key: records_written}. The commit is done by the caller.
        """
        with log_operation(logger, "fetch_all_prices"):
            shops = await self.shops.list_active()
            logger.info(f"Active shops to process: {[s.adapter_key for s in shops]}")

            results: dict[str, int] = {}
            for shop in shops:
                try:
                    results[shop.adapter_key] = await self._fetch_shop(shop)
                except Exception:
                    logger.exception(
                        f"Unhandled error fetching prices from shop={shop.adapter_key}"
                    )
                    results[shop.adapter_key] = 0

            logger.info(f"Price fetch summary: {results}")
            return results

    async def _fetch_shop(self, shop: Shop) -> int:
        with log_operation(
            logger, "fetch_shop_prices", adapter=shop.adapter_key, url=shop.base_url
        ):
            adapter = get_adapter(shop.adapter_key, shop.base_url)
            fetched = await adapter.fetch_products()
            logger.info(
                f"Fetched {len(fetched)} products from adapter={shop.adapter_key}"
            )

            ps_rows = await self.shops.list_product_shops(shop.id)
            ps_by_external_id = {ps.external_id: ps for ps in ps_rows}
            logger.info(
                f"Mapped {len(ps_by_external_id)} product_shop records "
                f"for adapter={shop.adapter_key}"
            )

            # Dedup: products whose price was already taken within the last hour.
            since = datetime.now(timezone.utc) - _DEDUP_WINDOW
            recently_priced = await self.prices.product_shop_ids_priced_since(since)

            count = 0
            skipped = 0
            deduped = 0
            for product in fetched:
                ps = ps_by_external_id.get(product.external_id)
                if ps is None:
                    skipped += 1
                    continue  # product is not mapped in the DB yet
                if ps.id in recently_priced:
                    deduped += 1
                    continue  # a fresh snapshot already exists — no duplicate
                self.prices.add_price(ps.id, product.price_usd)
                count += 1

            await self.prices.flush()

            if skipped:
                logger.warning(
                    f"Skipped {skipped} unmapped products | adapter={shop.adapter_key}"
                )
            if deduped:
                logger.info(
                    f"Deduped {deduped} products with a recent price "
                    f"(< {_DEDUP_WINDOW}) | adapter={shop.adapter_key}"
                )
            logger.info(
                f"Written {count} price_history records for adapter={shop.adapter_key}"
            )
            return count
