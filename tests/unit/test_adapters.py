"""Юнит-тесты адаптеров магазинов: маппинг ответов в ShopProduct, пагинация
DummyJSON и retry на 429. Сеть замокана фейковым httpx-клиентом."""

from decimal import Decimal

import httpx
import pytest

from app.services.shop_adapters.dummyjson import DummyJsonAdapter
from app.services.shop_adapters.fakestore import FakeStoreAdapter
from app.services.shop_adapters.registry import get_adapter


class _FakeResponse:
    def __init__(self, json_data, status_code: int = 200) -> None:
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


class _FakeClient:
    """Контекст-менеджер вместо httpx.AsyncClient; get() делегирует в handler."""

    def __init__(self, handler, **_) -> None:
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, url: str):
        return self._handler(url)


def _patch_client(monkeypatch, module: str, handler) -> None:
    monkeypatch.setattr(
        f"{module}.httpx.AsyncClient", lambda **kw: _FakeClient(handler)
    )


async def test_fakestore_maps_fields(monkeypatch):
    payload = [
        {"id": 1, "title": "Backpack", "price": 109.95,
         "description": "d", "category": "bags"},
        {"id": 2, "title": "T-Shirt", "price": 22.3,
         "description": "d2", "category": "clothes"},
    ]
    _patch_client(monkeypatch, "app.services.shop_adapters.fakestore",
                  lambda url: _FakeResponse(payload))

    products = await FakeStoreAdapter("https://fakestore").fetch_products()

    assert [p.external_id for p in products] == ["1", "2"]
    assert products[0].title == "Backpack"
    assert products[0].price_usd == Decimal("109.95")  # деньги — Decimal, не float
    assert isinstance(products[0].price_usd, Decimal)
    assert products[1].category == "clothes"


async def test_fakestore_retries_on_5xx(monkeypatch):
    monkeypatch.setattr("app.core.http_retry.asyncio.sleep", _noop_sleep)
    calls = {"n": 0}

    def handler(url: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(None, status_code=503)  # первый раз — сервис лёг
        return _FakeResponse([
            {"id": 1, "title": "P", "price": 5.0, "description": "", "category": "c"},
        ])

    _patch_client(monkeypatch, "app.services.shop_adapters.fakestore", handler)

    products = await FakeStoreAdapter("https://fakestore").fetch_products()

    assert calls["n"] == 2
    assert len(products) == 1


async def test_dummyjson_paginates(monkeypatch):
    # total=150 при limit=100 → две страницы (skip=0 и skip=100).
    def handler(url: str):
        skip = 100 if "skip=100" in url else 0
        count = 50 if skip == 100 else 100
        return _FakeResponse({
            "total": 150,
            "products": [
                {"id": skip + i, "title": f"P{skip + i}", "price": 1.0,
                 "description": "", "category": "c"}
                for i in range(count)
            ],
        })

    _patch_client(monkeypatch, "app.services.shop_adapters.dummyjson", handler)

    products = await DummyJsonAdapter("https://dummyjson").fetch_products()

    assert len(products) == 150
    assert products[0].external_id == "0"
    assert products[-1].external_id == "149"


async def test_dummyjson_retries_on_429(monkeypatch):
    monkeypatch.setattr("app.core.http_retry.asyncio.sleep", _noop_sleep)
    calls = {"n": 0}

    def handler(url: str):
        calls["n"] += 1
        if calls["n"] == 1:
            return _FakeResponse(None, status_code=429)  # первый раз — лимит
        return _FakeResponse({
            "total": 1,
            "products": [{"id": 1, "title": "P", "price": 5.0,
                          "description": "", "category": "c"}],
        })

    _patch_client(monkeypatch, "app.services.shop_adapters.dummyjson", handler)

    products = await DummyJsonAdapter("https://dummyjson").fetch_products()

    assert calls["n"] == 2  # один ретрай
    assert len(products) == 1


def test_registry_resolves_known_adapters():
    assert isinstance(get_adapter("dummyjson", "u"), DummyJsonAdapter)
    assert isinstance(get_adapter("fakestore", "u"), FakeStoreAdapter)
    with pytest.raises(KeyError):
        get_adapter("unknown", "u")


async def _noop_sleep(_seconds):
    return None
