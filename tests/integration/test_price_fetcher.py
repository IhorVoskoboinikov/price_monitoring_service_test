"""Test for PriceFetcherService: takes prices from all active shops through
adapters (mocked), writes to price_history only mapped products, and does not
duplicate a price taken recently (< 1 hour)."""

from decimal import Decimal

from sqlalchemy import delete, func, select

from app.db.models.price_history import PriceHistory
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.shop_repo import ShopRepo
from app.services.price_fetcher import PriceFetcherService
from app.services.shop_adapters.base import ShopProduct

# seed: dummyjson holds external_id "1"(p1) and "2"(p2), fakestore — "101"(p1).
ADAPTERS = {
    "dummyjson": [
        ShopProduct("1", "P1", "", "c", Decimal("20.0")),
        ShopProduct("2", "P2", "", "c", Decimal("30.0")),
        ShopProduct("999", "Ghost", "", "c", Decimal("1.0")),  # not mapped -> skipped
    ],
    "fakestore": [
        ShopProduct("101", "P1", "", "c", Decimal("25.0")),
    ],
}


class _FakeAdapter:
    def __init__(self, products: list[ShopProduct]) -> None:
        self._products = products

    async def fetch_products(self) -> list[ShopProduct]:
        return self._products


def _patch_adapters(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.price_fetcher.get_adapter",
        lambda adapter_key, base_url: _FakeAdapter(ADAPTERS[adapter_key]),
    )


async def _count_prices(db) -> int:
    return await db.scalar(select(func.count()).select_from(PriceHistory))


async def test_fetch_all_writes_prices_for_mapped_products(db, monkeypatch):
    _patch_adapters(monkeypatch)
    # remove the fresh seed prices so dedup does not kick in
    await db.execute(delete(PriceHistory))
    await db.commit()

    service = PriceFetcherService(ShopRepo(db), PriceRepo(db))
    results = await service.fetch_all()
    await db.commit()

    assert results == {"dummyjson": 2, "fakestore": 1}  # "999" skipped
    assert await _count_prices(db) == 3


async def test_fetch_all_dedupes_recent_prices(db, monkeypatch):
    _patch_adapters(monkeypatch)
    # the seed already has prices taken just now -> all fall into the dedup window
    before = await _count_prices(db)

    service = PriceFetcherService(ShopRepo(db), PriceRepo(db))
    results = await service.fetch_all()
    await db.commit()

    assert results == {"dummyjson": 0, "fakestore": 0}  # nothing was added
    assert await _count_prices(db) == before
