"""Юнит-тесты чистой логики (без БД и сети)."""

import uuid
from decimal import Decimal

from app.schemas.enums import Currency, SortOption, TrendDirection
from app.schemas.product import ProductListItem
from app.services.price_service import _determine_trend, _sort_items


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
        # +0.5% < порога 1%
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
