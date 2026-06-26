"""Unit tests for pure logic (no DB and no network)."""

import uuid
from decimal import Decimal

from app.schemas.enums import Currency, SortOption, TrendDirection
from app.schemas.product import ProductListItem
from app.services.price_service import _determine_trend, _sort_items
from app.services.shop_adapters.base import ShopProduct
from app.tasks.seed import _map_by_nearest_price


def _sp(price: str) -> ShopProduct:
    return ShopProduct(
        external_id="x", title="t", description="", category="c",
        price_usd=Decimal(price),
    )


def _item(price_min, price_max, trend):
    return ProductListItem(
        id=uuid.uuid4(),
        title="x",
        category=None,
        price_min=price_min,
        price_max=price_max,
        currency=Currency.USD,
        trend=trend,
    )


class TestDetermineTrend:
    def test_up(self):
        assert _determine_trend(Decimal("110"), Decimal("100")) == TrendDirection.UP

    def test_down(self):
        assert _determine_trend(Decimal("90"), Decimal("100")) == TrendDirection.DOWN

    def test_same_within_threshold(self):
        # +0.5% < the 1% threshold
        assert _determine_trend(Decimal("100.5"), Decimal("100")) == TrendDirection.SAME

    def test_same_on_missing_or_zero(self):
        assert _determine_trend(None, Decimal("100")) == TrendDirection.SAME
        assert _determine_trend(Decimal("100"), None) == TrendDirection.SAME
        assert _determine_trend(Decimal("100"), Decimal("0")) == TrendDirection.SAME


class TestSortItems:
    def test_price_asc(self):
        items = [
            _item(Decimal("30"), Decimal("30"), TrendDirection.SAME),
            _item(Decimal("10"), Decimal("10"), TrendDirection.SAME),
        ]
        out = _sort_items(items, SortOption.PRICE_ASC)
        assert [i.price_min for i in out] == [Decimal("10"), Decimal("30")]

    def test_price_desc(self):
        items = [
            _item(Decimal("10"), Decimal("10"), TrendDirection.SAME),
            _item(Decimal("30"), Decimal("30"), TrendDirection.SAME),
        ]
        out = _sort_items(items, SortOption.PRICE_DESC)
        assert [i.price_max for i in out] == [Decimal("30"), Decimal("10")]

    def test_none_price_sorts_last_on_asc(self):
        items = [
            _item(None, None, TrendDirection.SAME),
            _item(Decimal("10"), Decimal("10"), TrendDirection.SAME),
        ]
        out = _sort_items(items, SortOption.PRICE_ASC)
        assert out[0].price_min == Decimal("10")
        assert out[1].price_min is None

    def test_trend_desc_up_first(self):
        items = [
            _item(Decimal("1"), Decimal("1"), TrendDirection.DOWN),
            _item(Decimal("1"), Decimal("1"), TrendDirection.UP),
            _item(Decimal("1"), Decimal("1"), TrendDirection.SAME),
        ]
        out = _sort_items(items, SortOption.TREND_DESC)
        assert [i.trend for i in out] == [
            TrendDirection.UP,
            TrendDirection.SAME,
            TrendDirection.DOWN,
        ]


class TestMapByNearestPrice:
    def test_pairs_by_closest_price(self):
        dummy = [_sp("10"), _sp("100"), _sp("50")]
        fake = [_sp("52"), _sp("9")]
        mapping = _map_by_nearest_price(dummy, fake)
        # 52 -> idx 2 (price 50), 9 -> idx 0 (price 10)
        assert mapping[2].price_usd == Decimal("52")
        assert mapping[0].price_usd == Decimal("9")
        assert set(mapping) == {0, 2}

    def test_each_dummy_used_once(self):
        dummy = [_sp("10"), _sp("11")]
        fake = [_sp("10"), _sp("10")]  # both closest to idx 0
        mapping = _map_by_nearest_price(dummy, fake)
        assert set(mapping) == {0, 1}  # the second falls back to idx 1

    def test_stops_when_no_dummy_left(self):
        dummy = [_sp("10")]
        fake = [_sp("10"), _sp("20")]
        mapping = _map_by_nearest_price(dummy, fake)
        assert set(mapping) == {0}  # only one DummyJSON product to match
