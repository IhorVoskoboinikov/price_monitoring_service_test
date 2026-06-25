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

# Валюты для синхронизации с НБУ (UAH — опорная, её курс к себе = 1).
SYNC_CURRENCIES = [Currency.USD, Currency.EUR, Currency.GBP]


class CurrencyService:
    """Конвертация валют и доступ к курсам НБУ.

    Чтение курсов идёт через инжектируемый репозиторий (общая сессия запроса):
    Redis → БД → НБУ API. Сервис не открывает собственные сессии.
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
        """Конвертирует сумму из USD в нужную валюту.

        Все конвертации идут через гривну как промежуточную:
            USD → UAH :  price_usd * rate_usd
            USD → EUR :  price_usd * rate_usd / rate_eur
        """
        if to_currency == Currency.USD:
            return amount_usd

        target_date = for_date or date.today()
        rate_usd = await self.get_rate(Currency.USD, target_date)

        if to_currency == Currency.UAH:
            return (amount_usd * rate_usd).quantize(Decimal("0.0001"))

        rate_target = await self.get_rate(to_currency, target_date)
        return (amount_usd * rate_usd / rate_target).quantize(Decimal("0.0001"))

    async def get_rate(self, currency: Currency, for_date: date) -> Decimal:
        """Курс (гривен за 1 единицу валюты). Redis → БД → НБУ API.

        UAH — опорная валюта: 1 гривна за 1 гривну. Её нет ни в БД, ни в ответе
        НБУ, поэтому возвращаем 1 напрямую.
        """
        if currency == Currency.UAH:
            return Decimal(1)

        cache_key = f"exchange_rate:{currency}:{for_date}"

        cached = await self._redis.get(cache_key)
        if cached:
            return Decimal(cached)

        # 1. Точная дата в БД
        rate = await self._rates.get_rate(currency, for_date)
        if rate is not None:
            await self._cache(cache_key, rate, for_date)
            return rate

        # 2. НБУ on-demand (НБУ отдаёт курс и на выходные) + self-warming в БД
        rate = await self._fetch_from_nbu(currency, for_date)
        if rate is not None:
            await self._rates.upsert(currency, for_date, rate)
            await self._cache(cache_key, rate, for_date)
            return rate

        # 3. Fallback: ближайший предыдущий курс из БД (НБУ недоступен)
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
        """Сегодняшние курсы всех поддерживаемых валют из БД."""
        return await self._rates.list_for_date(date.today())

    # ── Sync (Celery / startup / on-demand) ───────────────────────────────

    async def sync_today_rates(self) -> int:
        """Загружает сегодняшние курсы всех валют с НБУ (bulk-запрос) в БД.

        Идемпотентно (upsert). Возвращает число обновлённых валют.
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
        """Догружает исторические курсы за диапазон (по дням, идемпотентно).

        Пропускает даты, уже имеющиеся в БД. Возвращает число записанных строк.
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
        """Сегодняшние курсы всех валют одним запросом к НБУ: {cc: rate}."""
        try:
            async with httpx.AsyncClient(timeout=settings.shop_api_timeout) as client:
                resp = await get_with_retry(
                    client,
                    f"{settings.nbu_api_url}?json",
                    attempts=settings.shop_api_retry_attempts,
                )
                return {r["cc"]: Decimal(str(r["rate"])) for r in resp.json()}
        except Exception as e:
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
        except Exception as e:
            logger.warning(f"NBU API failed for {currency} on {for_date}: {e}")
        return None

    async def _cache(self, key: str, rate: Decimal, for_date: date) -> None:
        # Текущий курс кешируем с TTL, исторический — бессрочно (он не меняется).
        ttl = settings.redis_ttl_exchange_rate if for_date == date.today() else None
        if ttl:
            await self._redis.set(key, str(rate), ex=ttl)
        else:
            await self._redis.set(key, str(rate))
