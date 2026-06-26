"""Tests for PriceService on real history data: computing the trend
(up/down vs the 30-day average) and building the price history by day.

Currency is USD, so conversion is identity here; the tests do not depend on
rates and do not go to the network."""

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
    # 30-day average is low (5.00) -> today's 12.99/15.99 are higher -> up
    ps_ids = await _product1_shop_ids(db)
    await _add_history(db, ps_ids, "5.00", days_ago=10)
    assert await _trend_of_product1(db) == TrendDirection.UP


async def test_trend_down_when_today_below_30d_avg(db):
    # 30-day average is high (50.00) -> today's prices are lower -> down
    ps_ids = await _product1_shop_ids(db)
    await _add_history(db, ps_ids, "50.00", days_ago=10)
    assert await _trend_of_product1(db) == TrendDirection.DOWN


async def test_trend_same_without_history(db):
    # no 30-day history (only today's records) -> SAME
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
    # two days with data: "3 days ago" and today
    assert len(resp.average) == 2


async def _one_today_one_stale(db) -> None:
    """Reconfigure product 1: one shop has a price today (12.99), the other
    has only an old price (999, 2 days ago)."""
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
    # spec: "today's price range" — a shop's yesterday price is not counted
    await _one_today_one_stale(db)
    detail = await _service(db).get_product_detail(PRODUCT_1_ID, Currency.USD)
    assert detail.price_min == Decimal("12.99")
    assert detail.price_max == Decimal("12.99")  # 999 (2 days ago) not in the range
    assert detail.shops_count == 2  # the shop exists, it just has no price today


async def test_current_prices_only_today(db):
    # /prices: "list of shop-price pairs for today" — stale records are not shown
    await _one_today_one_stale(db)
    prices = await _service(db).get_current_prices(PRODUCT_1_ID, Currency.USD)
    assert len(prices) == 1
    assert prices[0].price == Decimal("12.99")


async def test_product_detail_not_found_raises(db):
    with pytest.raises(NotFoundError):
        await _service(db).get_product_detail(uuid.uuid4(), Currency.USD)
