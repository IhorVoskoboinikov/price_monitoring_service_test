from datetime import date
from decimal import Decimal

from sqlalchemy import CHAR, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models.base import Base


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    currency_code: Mapped[str] = mapped_column(CHAR(3))
    rate_uah_per_unit: Mapped[Decimal] = mapped_column(Numeric(16, 8))
    date: Mapped[date] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, default="NBU")

    __table_args__ = (UniqueConstraint("currency_code", "date"),)
