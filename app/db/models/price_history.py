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
    Партиционированная таблица по recorded_at (RANGE по месяцам).
    Composite PK (id, recorded_at) — обязательно для партиционирования.
    Первую партицию создаём в миграции вручную, следующие — Celery-задачей.
    """

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_shop_id: Mapped[int] = mapped_column(ForeignKey("product_shops.id"))
    price_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), primary_key=True
    )

    __table_args__ = (
        # Покрывающий индекс под два горячих чтения самой большой таблицы:
        #  • «последняя цена магазина» (row_number OVER ... ORDER BY recorded_at DESC)
        #  • история/агрегаты по диапазону дат.
        # recorded_at DESC — под порядок «последней»; INCLUDE(price_usd) даёт
        # index-only scan (без обращения к heap). Заменяет прежний индекс,
        # а не добавляет — write-amplification не растёт.
        Index(
            "ix_price_history_lookup",
            "product_shop_id",
            desc("recorded_at"),
            postgresql_include=["price_usd"],
        ),
        {"postgresql_partition_by": "RANGE (recorded_at)"},
    )
