from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

import httpx
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.http_retry import get_with_retry
from app.core.logger import get_logger
from app.db.models.exchange_rate import ExchangeRate
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.schemas.enums import Currency

logger = get_logger(__name__)

# Currencies to sync from NBU (UAH is the base; its rate to itself = 1).
SYNC_CURRENCIES = [Currency.USD, Currency.EUR, Currency.GBP]

# Money precision of the conversion result — always 4 digits.
_MONEY = Decimal("0.0001")

# Expected failures when calling NBU: network/HTTP, broken JSON, partial answer,
# non-numeric rate. We catch only these (graceful degradation), not every Exception,
# so code bugs (AttributeError, NameError, etc.) are not hidden.
_NBU_FETCH_ERRORS = (httpx.HTTPError, ValueError, KeyError, TypeError, ArithmeticError)


class CurrencyService:
    """Currency conversion and access to NBU rates.

    Rates are read through an injected repository (the shared request session):
    Redis -> DB -> NBU API. The service does not open its own sessions.
    """

    def __init__(self, rates: ExchangeRateRepo, redis: aioredis.Redis) -> None:
        self._rates = rates
        self._redis = redis

    # ── Public API ────────────────────────────────────────────────────────

    async def convert(
        self,
        amount_usd: Decimal,
        to_currency: Currency,
        for_date: date | None = None,
    ) -> Decimal:
        """Convert an amount from USD to the wanted currency.

        Every conversion goes through the hryvnia as a middle step:
            USD -> UAH :  price_usd * rate_usd
            USD -> EUR :  price_usd * rate_usd / rate_eur
        """
        if to_currency == Currency.USD:
            return amount_usd.quantize(_MONEY)

        target_date = for_date or date.today()
        rate_usd = await self.get_rate(Currency.USD, target_date)

        if to_currency == Currency.UAH:
            return (amount_usd * rate_usd).quantize(_MONEY)

        rate_target = await self.get_rate(to_currency, target_date)
        return (amount_usd * rate_usd / rate_target).quantize(_MONEY)

    async def get_rate(self, currency: Currency, for_date: date) -> Decimal:
        """Rate (hryvnias per 1 unit of currency). Redis -> DB -> NBU API.

        UAH is the base currency: 1 hryvnia per 1 hryvnia. It is not in the DB or in
        the NBU answer, so we return 1 directly.
        """
        if currency == Currency.UAH:
            return Decimal(1)

        cache_key = f"exchange_rate:{currency}:{for_date}"

        cached = await self._redis.get(cache_key)
        if cached:
            return Decimal(cached)

        # 1. Exact date in the DB
        rate = await self._rates.get_rate(currency, for_date)
        if rate is not None:
            await self._cache(cache_key, rate, for_date)
            return rate

        # 2. NBU on-demand (NBU also gives a rate on weekends) + self-warming into DB
        rate = await self._fetch_from_nbu(currency, for_date)
        if rate is not None:
            await self._rates.upsert(currency, for_date, rate)
            await self._cache(cache_key, rate, for_date)
            return rate

        # 3. Fallback: nearest earlier rate from the DB (NBU is down)
        rate = await self._rates.get_rate_on_or_before(currency, for_date)
        if rate is not None:
            logger.warning(
                f"Rate for {currency} on {for_date} unavailable — "
                f"using nearest earlier rate from DB"
            )
            await self._cache(cache_key, rate, for_date)
            return rate

        raise ValueError(f"Exchange rate for {currency} on {for_date} not available")

    async def get_today_rates(self) -> Sequence[ExchangeRate]:
        """Today's rates for all supported currencies from the DB."""
        return await self._rates.list_for_date(date.today())

    # ── Sync (Celery / startup / on-demand) ───────────────────────────────

    async def sync_today_rates(self) -> int:
        """Load today's rates for all currencies from NBU (bulk request) into the DB.

        Idempotent (upsert). Returns the number of updated currencies.
        """
        today = date.today()
        rates = await self._fetch_all_today_from_nbu()
        synced = 0
        for currency in SYNC_CURRENCIES:
            if currency not in rates:
                logger.warning(f"NBU response has no rate for {currency}")
                continue
            await self._rates.upsert(currency, today, rates[currency])
            await self._cache(
                f"exchange_rate:{currency}:{today}", rates[currency], today
            )
            synced += 1
        logger.info(f"sync_today_rates done | date={today} synced={synced}")
        return synced

    async def sync_historical_rates(self, date_from: date, date_to: date) -> int:
        """Load historical rates for a date range (day by day, idempotent).

        Skips dates already present in the DB. Returns the number of written rows.
        """
        written = 0
        current = date_from
        while current <= date_to:
            for currency in SYNC_CURRENCIES:
                if await self._rates.get_rate(currency, current) is not None:
                    continue
                rate = await self._fetch_from_nbu(currency, current)
                if rate is not None:
                    await self._rates.upsert(currency, current, rate)
                    written += 1
            current += timedelta(days=1)
        logger.info(
            f"sync_historical_rates done | {date_from}..{date_to} written={written}"
        )
        return written

    # ── Internals ─────────────────────────────────────────────────────────

    async def _fetch_all_today_from_nbu(self) -> dict[str, Decimal]:
        """Today's rates for all currencies in one NBU request: {cc: rate}."""
        try:
            async with httpx.AsyncClient(timeout=settings.shop_api_timeout) as client:
                resp = await get_with_retry(
                    client,
                    f"{settings.nbu_api_url}?json",
                    attempts=settings.shop_api_retry_attempts,
                )
                return {r["cc"]: Decimal(str(r["rate"])) for r in resp.json()}
        except _NBU_FETCH_ERRORS as e:
            logger.warning(f"NBU bulk fetch failed: {e}")
            return {}

    async def _fetch_from_nbu(self, currency: str, for_date: date) -> Decimal | None:
        date_str = for_date.strftime("%Y%m%d")
        url = f"{settings.nbu_api_url}?valcode={currency}&date={date_str}&json"
        try:
            async with httpx.AsyncClient(timeout=settings.shop_api_timeout) as client:
                resp = await get_with_retry(
                    client, url, attempts=settings.shop_api_retry_attempts
                )
                data = resp.json()
            if data:
                return Decimal(str(data[0]["rate"]))
        except _NBU_FETCH_ERRORS as e:
            logger.warning(f"NBU API failed for {currency} on {for_date}: {e}")
        return None

    async def _cache(self, key: str, rate: Decimal, for_date: date) -> None:
        # Cache today's rate with a TTL; a historical one forever (it does not change).
        ttl = settings.redis_ttl_exchange_rate if for_date == date.today() else None
        if ttl:
            await self._redis.set(key, str(rate), ex=ttl)
        else:
            await self._redis.set(key, str(rate))
