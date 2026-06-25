from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models.exchange_rate import ExchangeRate
from app.db.repositories.base import BaseRepository


class ExchangeRateRepo(BaseRepository):
    """Доступ к таблице exchange_rates."""

    async def get_rate(self, currency: str, for_date: date) -> Decimal | None:
        return await self.db.scalar(
            select(ExchangeRate.rate_uah_per_unit).where(
                ExchangeRate.currency_code == currency,
                ExchangeRate.date == for_date,
            )
        )

    async def get_rate_on_or_before(
        self, currency: str, for_date: date
    ) -> Decimal | None:
        """Ближайший курс на дату ≤ for_date (fallback, когда точной даты нет)."""
        return await self.db.scalar(
            select(ExchangeRate.rate_uah_per_unit)
            .where(
                ExchangeRate.currency_code == currency,
                ExchangeRate.date <= for_date,
            )
            .order_by(ExchangeRate.date.desc())
            .limit(1)
        )

    async def list_for_date(self, for_date: date) -> Sequence[ExchangeRate]:
        rows = (
            await self.db.execute(
                select(ExchangeRate).where(ExchangeRate.date == for_date)
            )
        ).scalars().all()
        return rows

    async def upsert(
        self, currency: str, for_date: date, rate: Decimal, source: str = "NBU"
    ) -> None:
        """Идемпотентная запись курса по уникальному ключу (currency_code, date)."""
        stmt = pg_insert(ExchangeRate).values(
            currency_code=currency,
            rate_uah_per_unit=rate,
            date=for_date,
            source=source,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["currency_code", "date"],
            set_={"rate_uah_per_unit": rate, "source": source},
        )
        await self.db.execute(stmt)
