"""Тест PriceFetcherService: снимает цены со всех активных магазинов через
адаптеры (замокано), пишет в price_history только смапленные товары и
не дублирует цену, снятую недавно (< 1 часа)."""

from decimal import Decimal

from sqlalchemy import delete, func, select

from app.db.models.price_history import PriceHistory
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.shop_repo import ShopRepo
from app.services.price_fetcher import PriceFetcherService
from app.services.shop_adapters.base import ShopProduct

# seed: dummyjson хранит external_id "1"(p1) и "2"(p2), fakestore — "101"(p1).
ADAPTERS = {
    "dummyjson": [
        ShopProduct("1", "P1", "", "c", Decimal("20.0")),
        ShopProduct("2", "P2", "", "c", Decimal("30.0")),
        ShopProduct("999", "Ghost", "", "c", Decimal("1.0")),  # не смаплен → пропуск
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
    # убираем свежие seed-цены, чтобы дедуп не сработал
    await db.execute(delete(PriceHistory))
    await db.commit()

    service = PriceFetcherService(ShopRepo(db), PriceRepo(db))
    results = await service.fetch_all()
    await db.commit()

    assert results == {"dummyjson": 2, "fakestore": 1}  # "999" пропущен
    assert await _count_prices(db) == 3


async def test_fetch_all_dedupes_recent_prices(db, monkeypatch):
    _patch_adapters(monkeypatch)
    # seed уже содержит цены, снятые сейчас → все попадают в окно дедупа
    before = await _count_prices(db)

    service = PriceFetcherService(ShopRepo(db), PriceRepo(db))
    results = await service.fetch_all()
    await db.commit()

    assert results == {"dummyjson": 0, "fakestore": 0}  # ничего не дописано
    assert await _count_prices(db) == before
