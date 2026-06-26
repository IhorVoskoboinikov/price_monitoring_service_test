from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    desc,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class PriceHistory(Base):
    """
    Table partitioned by recorded_at (RANGE by month).
    Composite PK (id, recorded_at) is required for partitioning.
    We create the first partition by hand in a migration; the next ones by a
    Celery task.
    """

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_shop_id: Mapped[int] = mapped_column(ForeignKey("product_shops.id"))
    price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), primary_key=True
    )

    __table_args__ = (
        # Covering index for the two hot reads of the biggest table:
        #  • "last price per shop" (row_number OVER ... ORDER BY recorded_at DESC)
        #  • history / aggregates over a date range.
        # recorded_at DESC matches the "last" order; INCLUDE(price_usd) gives an
        # index-only scan (no heap lookup). It replaces the old index instead of
        # adding one, so write amplification does not grow.
        Index(
            "ix_price_history_lookup",
            "product_shop_id",
            desc("recorded_at"),
            postgresql_include=["price_usd"],
        ),
        {"postgresql_partition_by": "RANGE (recorded_at)"},
    )
