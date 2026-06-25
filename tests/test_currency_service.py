"""Юнит/интеграционные тесты CurrencyService: конвертация через гривну, кеш,
загрузка с НБУ on-demand, fallback и sync. БД — тестовый Postgres, НБУ замокан."""

from datetime import date, timedelta
from decimal import Decimal

import fakeredis.aioredis

from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.schemas.enums import Currency
from app.services.currency_service import CurrencyService

USD_RATE = Decimal("44.8685")
EUR_RATE = Decimal("50.8809")


def _service(db, redis=None) -> CurrencyService:
    return CurrencyService(
        ExchangeRateRepo(db),
        redis or fakeredis.aioredis.FakeRedis(decode_responses=True),
    )


async def test_uah_rate_is_one(db):
    assert await _service(db).get_rate(Currency.UAH, date.today()) == Decimal(1)


async def test_convert_usd_returns_same(db):
    assert await _service(db).convert(Decimal("10"), Currency.USD) == Decimal("10")


async def test_convert_to_uah(db):
    out = await _service(db).convert(Decimal("12.99"), Currency.UAH)
    assert out == (Decimal("12.99") * USD_RATE).quantize(Decimal("0.0001"))


async def test_convert_to_eur_cross_rate(db):
    out = await _service(db).convert(Decimal("12.99"), Currency.EUR)
    assert out == (Decimal("12.99") * USD_RATE / EUR_RATE).quantize(Decimal("0.0001"))


async def test_get_rate_uses_cache(db):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    today = date.today()
    await redis.set(f"exchange_rate:{Currency.USD}:{today}", "99.0")
    # курс берётся из кеша, БД (где 44.8685) не трогается
    assert await _service(db, redis).get_rate(Currency.USD, today) == Decimal("99.0")


async def test_get_rate_fetches_from_nbu_when_missing(db, monkeypatch):
    svc = _service(db)
    past = date.today() - timedelta(days=400)  # точно нет в seed

    async def fake_fetch(currency, for_date):
        return Decimal("38.5")

    monkeypatch.setattr(svc, "_fetch_from_nbu", fake_fetch)

    rate = await svc.get_rate(Currency.USD, past)
    assert rate == Decimal("38.5")
    # self-warming: курс осел в БД
    assert await ExchangeRateRepo(db).get_rate(Currency.USD, past) == Decimal("38.5")


async def test_get_rate_falls_back_to_earlier_when_nbu_down(db, monkeypatch):
    svc = _service(db)
    future = date.today() + timedelta(days=5)

    async def nbu_down(currency, for_date):
        return None

    monkeypatch.setattr(svc, "_fetch_from_nbu", nbu_down)

    # НБУ молчит, точной даты нет → ближайший предыдущий (сегодняшний) курс
    assert await svc.get_rate(Currency.USD, future) == USD_RATE


async def test_sync_today_rates(db, monkeypatch):
    svc = _service(db)

    async def fake_bulk():
        return {"USD": Decimal("45.0"), "EUR": Decimal("51.0"), "GBP": Decimal("60.0")}

    monkeypatch.setattr(svc, "_fetch_all_today_from_nbu", fake_bulk)

    synced = await svc.sync_today_rates()
    await db.commit()

    assert synced == 3
    stored = await ExchangeRateRepo(db).get_rate(Currency.USD, date.today())
    assert stored == Decimal("45.0")
