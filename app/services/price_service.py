import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from app.core.exceptions import NotFoundError
from app.core.logger import get_logger
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.product_repo import ProductRepo
from app.schemas.enums import Currency, SortOption, TrendDirection
from app.schemas.price import (
    PriceHistoryPoint,
    PriceHistoryResponse,
    PriceHistorySeries,
    ShopPriceItem,
)
from app.schemas.product import ProductDetail, ProductListItem, ProductListResponse
from app.services.currency_service import CurrencyService

logger = get_logger(__name__)

_TREND_THRESHOLD = Decimal("0.01")


def _determine_trend(
    avg_today: Decimal | None, avg_30d: Decimal | None
) -> TrendDirection:
    if not avg_today or not avg_30d or avg_30d == 0:
        return TrendDirection.SAME
    ratio = avg_today / avg_30d
    if ratio > 1 + _TREND_THRESHOLD:
        return TrendDirection.UP
    if ratio < 1 - _TREND_THRESHOLD:
        return TrendDirection.DOWN
    return TrendDirection.SAME


class PriceService:
    def __init__(
        self,
        products: ProductRepo,
        prices: PriceRepo,
        currency: CurrencyService,
    ) -> None:
        self.products = products
        self.prices = prices
        self.currency = currency

    # ── Product list (user's watchlist) ───────────────────────────────────

    async def get_products_list(
        self,
        user_id: uuid.UUID,
        currency: Currency,
        page: int,
        page_size: int,
        sort: SortOption,
    ) -> ProductListResponse:
        rows = await self.products.list_watchlist_with_prices(user_id)

        product_ids = [row.id for row in rows]
        today_map = await self.prices.avg_today_by_products(product_ids)
        hist_map = await self.prices.avg_prev_30d_by_products(product_ids)

        items: list[ProductListItem] = []
        for row in rows:
            trend = _determine_trend(today_map.get(row.id), hist_map.get(row.id))
            items.append(
                ProductListItem(
                    id=row.id,
                    title=row.title,
                    category=row.category,
                    price_min=await self._convert_opt(row.price_min, currency),
                    price_max=await self._convert_opt(row.price_max, currency),
                    currency=currency,
                    trend=trend,
                )
            )

        items = _sort_items(items, sort)

        total = len(items)
        offset = (page - 1) * page_size
        return ProductListResponse(
            items=items[offset : offset + page_size],
            page=page,
            page_size=page_size,
            total=total,
        )

    # ── Product detail ────────────────────────────────────────────────────

    async def get_product_detail(
        self, product_id: uuid.UUID, currency: Currency
    ) -> ProductDetail:
        row = await self.products.get_detail(product_id)
        if row is None:
            raise NotFoundError("Product not found")

        return ProductDetail(
            id=row.id,
            title=row.title,
            description=row.description,
            category=row.category,
            price_min=await self._convert_opt(row.price_min, currency),
            price_max=await self._convert_opt(row.price_max, currency),
            currency=currency,
            shops_count=row.shops_count,
        )

    async def get_watchlist_details(
        self, user_id: uuid.UUID, currency: Currency
    ) -> list[ProductDetail]:
        """Cards for all watched products in one query (no N+1)."""
        rows = await self.products.list_watchlist_details(user_id)
        return [
            ProductDetail(
                id=row.id,
                title=row.title,
                description=row.description,
                category=row.category,
                price_min=await self._convert_opt(row.price_min, currency),
                price_max=await self._convert_opt(row.price_max, currency),
                currency=currency,
                shops_count=row.shops_count,
            )
            for row in rows
        ]

    # ── Current prices per shop ───────────────────────────────────────────

    async def get_current_prices(
        self, product_id: uuid.UUID, currency: Currency
    ) -> list[ShopPriceItem]:
        rows = await self.prices.get_current_prices(product_id)
        if not rows and not await self.products.exists(product_id):
            raise NotFoundError("Product not found")

        result = []
        for row in rows:
            price = await self.currency.convert(row.price_usd, currency)
            result.append(
                ShopPriceItem(
                    shop_name=row.shop_name,
                    price=price,
                    currency=currency,
                    last_updated=row.recorded_at,
                )
            )
        return result

    # ── Price history ─────────────────────────────────────────────────────

    async def get_price_history(
        self,
        product_id: uuid.UUID,
        currency: Currency,
        date_from: date,
        date_to: date,
    ) -> PriceHistoryResponse:
        dt_from = datetime.combine(date_from, datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
        dt_to = datetime.combine(date_to, datetime.max.time()).replace(
            tzinfo=timezone.utc
        )

        rows = await self.prices.get_history(product_id, dt_from, dt_to)

        series_map: dict[str, list[PriceHistoryPoint]] = defaultdict(list)
        daily_all: dict[date, list[Decimal]] = defaultdict(list)

        for row in rows:
            point_date: date = row.day
            converted = await self.currency.convert(
                Decimal(str(row.avg_price_usd)), currency, for_date=point_date
            )
            series_map[row.shop_name].append(
                PriceHistoryPoint(date=point_date, price=converted)
            )
            daily_all[point_date].append(converted)

        series = [
            PriceHistorySeries(shop_name=name, data=points)
            for name, points in series_map.items()
        ]

        average = [
            PriceHistoryPoint(
                date=d,
                price=(sum(prices) / len(prices)).quantize(Decimal("0.0001")),
            )
            for d, prices in sorted(daily_all.items())
        ]

        return PriceHistoryResponse(series=series, average=average)

    # ── Helpers ───────────────────────────────────────────────────────────

    async def _convert_opt(
        self, amount_usd: Decimal | None, currency: Currency
    ) -> Decimal | None:
        if amount_usd is None:
            return None
        return await self.currency.convert(amount_usd, currency)


def _sort_items(
    items: list[ProductListItem], sort: SortOption
) -> list[ProductListItem]:
    if sort == SortOption.PRICE_ASC:
        return sorted(items, key=lambda x: (x.price_min is None, x.price_min or 0))
    if sort == SortOption.PRICE_DESC:
        return sorted(
            items, key=lambda x: (x.price_max is None, x.price_max or 0), reverse=True
        )
    if sort == SortOption.TREND_ASC:
        order = {TrendDirection.DOWN: 0, TrendDirection.SAME: 1, TrendDirection.UP: 2}
        return sorted(items, key=lambda x: order[x.trend])
    if sort == SortOption.TREND_DESC:
        order = {TrendDirection.UP: 0, TrendDirection.SAME: 1, TrendDirection.DOWN: 2}
        return sorted(items, key=lambda x: order[x.trend])
    return items
