import uuid
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import Row, Subquery, func, select

from app.db.models.price_history import PriceHistory
from app.db.models.product_shop import ProductShop
from app.db.models.shop import Shop
from app.db.repositories.base import BaseRepository


def utc_today_start() -> datetime:
    """Start of the current UTC day — the boundary for "today" queries."""
    return datetime.combine(date.today(), datetime.min.time()).replace(
        tzinfo=timezone.utc
    )


def latest_price_subq(since: datetime | None = None) -> Subquery:
    """Subquery: the last price (price_usd) for each product_shop_id.

    If `since` is given, only records not older than `since` are used — this gives
    the "today" price (from the spec): a shop with no record in the period drops out.
    """
    rn = func.row_number().over(
        partition_by=PriceHistory.product_shop_id,
        order_by=PriceHistory.recorded_at.desc(),
    ).label("rn")
    inner_q = select(
        PriceHistory.product_shop_id,
        PriceHistory.price_usd,
        PriceHistory.recorded_at,
        rn,
    )
    if since is not None:
        inner_q = inner_q.where(PriceHistory.recorded_at >= since)
    inner = inner_q.subquery()
    return (
        select(
            inner.c.product_shop_id,
            inner.c.price_usd,
            inner.c.recorded_at,
        )
        .where(inner.c.rn == 1)
        .subquery()
    )


class PriceRepo(BaseRepository):
    """Access to the price_history table."""

    async def get_current_prices(self, product_id: uuid.UUID) -> Sequence[Row]:
        """Today's shop prices for a product: (shop_name, price_usd, recorded_at).

        Shops with no record for today are not returned (spec: "prices for today").
        """
        latest = latest_price_subq(utc_today_start())
        q = (
            select(
                Shop.name.label("shop_name"),
                latest.c.price_usd,
                latest.c.recorded_at,
            )
            .join(ProductShop, ProductShop.id == latest.c.product_shop_id)
            .join(Shop, Shop.id == ProductShop.shop_id)
            .where(ProductShop.product_id == product_id)
        )
        return (await self.db.execute(q)).all()

    async def get_history(
        self, product_id: uuid.UUID, dt_from: datetime, dt_to: datetime
    ) -> Sequence[Row]:
        """Average daily price per shop: (shop_name, day, avg_price_usd)."""
        q = (
            select(
                Shop.name.label("shop_name"),
                func.date(PriceHistory.recorded_at).label("day"),
                func.avg(PriceHistory.price_usd).label("avg_price_usd"),
            )
            .join(ProductShop, PriceHistory.product_shop_id == ProductShop.id)
            .join(Shop, ProductShop.shop_id == Shop.id)
            .where(
                ProductShop.product_id == product_id,
                PriceHistory.recorded_at >= dt_from,
                PriceHistory.recorded_at <= dt_to,
            )
            .group_by(Shop.name, func.date(PriceHistory.recorded_at))
            .order_by(Shop.name, func.date(PriceHistory.recorded_at))
        )
        return (await self.db.execute(q)).all()

    async def avg_today_by_products(
        self, product_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Decimal]:
        """Average price for today for each product in the list."""
        if not product_ids:
            return {}
        today_start = utc_today_start()
        q = (
            select(
                ProductShop.product_id,
                func.avg(PriceHistory.price_usd).label("avg"),
            )
            .join(PriceHistory, PriceHistory.product_shop_id == ProductShop.id)
            .where(
                ProductShop.product_id.in_(product_ids),
                PriceHistory.recorded_at >= today_start,
            )
            .group_by(ProductShop.product_id)
        )
        rows = (await self.db.execute(q)).all()
        return {row.product_id: Decimal(str(row.avg)) for row in rows}

    async def avg_prev_30d_by_products(
        self, product_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, Decimal]:
        """Average price over the previous 30 days (up to today) for each product."""
        if not product_ids:
            return {}
        today_start = utc_today_start()
        cutoff = today_start - timedelta(days=30)
        q = (
            select(
                ProductShop.product_id,
                func.avg(PriceHistory.price_usd).label("avg"),
            )
            .join(PriceHistory, PriceHistory.product_shop_id == ProductShop.id)
            .where(
                ProductShop.product_id.in_(product_ids),
                PriceHistory.recorded_at >= cutoff,
                PriceHistory.recorded_at < today_start,
            )
            .group_by(ProductShop.product_id)
        )
        rows = (await self.db.execute(q)).all()
        return {row.product_id: Decimal(str(row.avg)) for row in rows}

    def add_price(self, product_shop_id: int, price_usd: Decimal) -> None:
        self.db.add(
            PriceHistory(product_shop_id=product_shop_id, price_usd=price_usd)
        )

    async def product_shop_ids_priced_since(self, since: datetime) -> set[int]:
        """product_shop_id values with a price record not older than `since`.

        Used for deduplication: we do not write a repeated price snapshot if one
        was taken recently (see PriceFetcherService).
        """
        rows = (
            await self.db.execute(
                select(PriceHistory.product_shop_id)
                .where(PriceHistory.recorded_at >= since)
                .distinct()
            )
        ).scalars().all()
        return set(rows)
