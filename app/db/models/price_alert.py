import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    desc,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id"))
    threshold_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    currency_code: Mapped[str | None] = mapped_column(CHAR(3), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Список алертов юзера: WHERE user_id ORDER BY created_at DESC.
        # Композит закрывает и фильтр, и сортировку.
        Index("ix_price_alert_user_created", "user_id", desc("created_at")),
        # Проверка срабатывания смотрит только активные. После срабатывания
        # алерт деактивируется → таблица со временем в основном «мёртвая».
        # Partial-индекс по живым строкам меньше и быстрее полного.
        Index(
            "ix_price_alert_active",
            "product_id",
            postgresql_where=text("is_active"),
        ),
    )
