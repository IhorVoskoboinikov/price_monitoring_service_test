"""Юнит-тесты UserProductService: список отслеживаемого, добавление с
проверками (404/409) и удаление (404). БД — тестовый Postgres."""

import uuid

import fakeredis.aioredis
import pytest
from fastapi import HTTPException

from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.db.repositories.price_repo import PriceRepo
from app.db.repositories.product_repo import ProductRepo
from app.db.repositories.user_product_repo import UserProductRepo
from app.schemas.enums import Currency
from app.services.currency_service import CurrencyService
from app.services.price_service import PriceService
from app.services.user_product_service import UserProductService
from tests.conftest import DEMO_USER_ID, PRODUCT_1_ID, PRODUCT_2_ID


def _service(db) -> UserProductService:
    currency = CurrencyService(
        ExchangeRateRepo(db), fakeredis.aioredis.FakeRedis(decode_responses=True)
    )
    price_service = PriceService(ProductRepo(db), PriceRepo(db), currency)
    return UserProductService(UserProductRepo(db), ProductRepo(db), price_service)


async def test_list_tracked_returns_details(db):
    # demo-юзер отслеживает только product 1
    tracked = await _service(db).list_tracked(DEMO_USER_ID, Currency.USD)
    assert [d.id for d in tracked] == [PRODUCT_1_ID]
    assert tracked[0].title == "Test Product 1"


async def test_add_success(db):
    svc = _service(db)
    await svc.add(DEMO_USER_ID, PRODUCT_2_ID)
    await db.commit()
    ids = {d.id for d in await svc.list_tracked(DEMO_USER_ID)}
    assert ids == {PRODUCT_1_ID, PRODUCT_2_ID}


async def test_add_nonexistent_product_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        await _service(db).add(DEMO_USER_ID, uuid.uuid4())
    assert exc.value.status_code == 404


async def test_add_duplicate_raises_409(db):
    with pytest.raises(HTTPException) as exc:
        await _service(db).add(DEMO_USER_ID, PRODUCT_1_ID)  # уже в watchlist
    assert exc.value.status_code == 409


async def test_remove_success(db):
    svc = _service(db)
    await svc.remove(DEMO_USER_ID, PRODUCT_1_ID)
    await db.commit()
    assert await svc.list_tracked(DEMO_USER_ID) == []


async def test_remove_not_tracked_raises_404(db):
    with pytest.raises(HTTPException) as exc:
        await _service(db).remove(DEMO_USER_ID, PRODUCT_2_ID)  # не отслеживается
    assert exc.value.status_code == 404
