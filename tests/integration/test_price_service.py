"""Тесты PriceService на реальных данных истории: вычисление тренда
(рост/падение vs среднее за 30 дней) и сборка истории цен по дням.

Валюта USD — конвертация при этом тождественна, поэтому тесты не зависят
от курсов и не ходят в сеть."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import fakeredis.aioredis
import pytest
from sqlalchemy import delete, select

from app.core.exceptions import NotFoundError
from app.db.models.price_history import PriceHistory
from app.db.models.product_shop import ProductShop
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.product_repo import ProductRepo
from app.schemas.enums import Currency, SortOption, TrendDirection
from app.services.currency_service import CurrencyService
from app.services.price_service import PriceService
from tests.conftest import DEMO_USER_ID, PRODUCT_1_ID


def _service(db) -> PriceService:
    currency = CurrencyService(
        ExchangeRateRepo(db), fakeredis.aioredis.FakeRedis(decode_responses=True)
    )
    return PriceService(ProductRepo(db), PriceRepo(db), currency)


async def _product1_shop_ids(db) -> list[int]:
    rows = (
        await db.execute(
            select(ProductShop.id).where(ProductShop.product_id == PRODUCT_1_ID)
        )
    ).scalars().all()
    return list(rows)


async def _add_history(db, ps_ids, price: str, days_ago: int) -> None:
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for ps_id in ps_ids:
        db.add(PriceHistory(product_shop_id=ps_id, price_usd=Decimal(price),
                            recorded_at=when))
    await db.commit()


async def _trend_of_product1(db) -> TrendDirection:
    resp = await _service(db).get_products_list(
        DEMO_USER_ID, Currency.USD, page=1, page_size=10, sort=SortOption.PRICE_ASC
    )
    item = next(i for i in resp.items if i.id == PRODUCT_1_ID)
    return item.trend


async def test_trend_up_when_today_above_30d_avg(db):
    # 30-дневное среднее низкое (5.00) → сегодняшние 12.99/15.99 выше → рост
    ps_ids = await _product1_shop_ids(db)
    await _add_history(db, ps_ids, "5.00", days_ago=10)
    assert await _trend_of_product1(db) == TrendDirection.UP


async def test_trend_down_when_today_below_30d_avg(db):
    # 30-дневное среднее высокое (50.00) → сегодняшние цены ниже → падение
    ps_ids = await _product1_shop_ids(db)
    await _add_history(db, ps_ids, "50.00", days_ago=10)
    assert await _trend_of_product1(db) == TrendDirection.DOWN


async def test_trend_same_without_history(db):
    # истории за 30 дней нет (только сегодняшние записи) → SAME
    assert await _trend_of_product1(db) == TrendDirection.SAME


async def test_price_history_groups_by_shop_and_day(db):
    ps_ids = await _product1_shop_ids(db)
    await _add_history(db, ps_ids, "10.00", days_ago=3)

    today = datetime.now(timezone.utc).date()
    resp = await _service(db).get_price_history(
        PRODUCT_1_ID, Currency.USD,
        date_from=today - timedelta(days=5), date_to=today,
    )

    assert {s.shop_name for s in resp.series} == {"DummyJSON", "FakeStore"}
    # два дня с данными: «3 дня назад» и сегодня
    assert len(resp.average) == 2


async def _one_today_one_stale(db) -> None:
    """Перенастраивает product 1: один магазин с ценой сегодня (12.99),
    второй — только со старой ценой (999, 2 дня назад)."""
    ps_ids = await _product1_shop_ids(db)
    await db.execute(
        delete(PriceHistory).where(PriceHistory.product_shop_id.in_(ps_ids))
    )
    now = datetime.now(timezone.utc)
    db.add(PriceHistory(product_shop_id=ps_ids[0], price_usd=Decimal("12.99"),
                        recorded_at=now))
    db.add(PriceHistory(product_shop_id=ps_ids[1], price_usd=Decimal("999.00"),
                        recorded_at=now - timedelta(days=2)))
    await db.commit()


async def test_today_range_excludes_stale_shop(db):
    # ТЗ: «диапазон цен на сегодня» — вчерашняя цена магазина не учитывается
    await _one_today_one_stale(db)
    detail = await _service(db).get_product_detail(PRODUCT_1_ID, Currency.USD)
    assert detail.price_min == Decimal("12.99")
    assert detail.price_max == Decimal("12.99")  # 999 (2 дня назад) не в диапазоне
    assert detail.shops_count == 2  # магазин существует, просто без цены за сегодня


async def test_current_prices_only_today(db):
    # /prices: «список пар магазин-цена на сегодня» — устаревшие записи не выводятся
    await _one_today_one_stale(db)
    prices = await _service(db).get_current_prices(PRODUCT_1_ID, Currency.USD)
    assert len(prices) == 1
    assert prices[0].price == Decimal("12.99")


async def test_product_detail_not_found_raises(db):
    with pytest.raises(NotFoundError):
        await _service(db).get_product_detail(uuid.uuid4(), Currency.USD)
