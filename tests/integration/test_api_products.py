"""API-тесты: список товаров, карточка, цены, история, конвертация валют."""

import uuid
from decimal import Decimal

from tests.conftest import PRODUCT_1_ID

USD_RATE = Decimal("44.8685")


async def test_products_list_returns_watchlist_only(auth_client):
    resp = await auth_client.get("/api/v1/products")
    assert resp.status_code == 200
    body = resp.json()
    # demo-юзер отслеживает только product 1
    assert body["total"] == 1
    item = body["items"][0]
    assert item["id"] == str(PRODUCT_1_ID)
    assert item["price_min"] == "12.9900"
    assert item["price_max"] == "15.9900"
    assert item["currency"] == "USD"


async def test_product_detail(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{PRODUCT_1_ID}")
    assert resp.status_code == 200
    d = resp.json()
    assert d["title"] == "Test Product 1"
    assert d["shops_count"] == 2
    assert d["price_min"] == "12.9900"
    assert d["price_max"] == "15.9900"


async def test_product_detail_not_found(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_product_prices_per_shop(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{PRODUCT_1_ID}/prices")
    assert resp.status_code == 200
    prices = resp.json()
    assert {p["shop_name"] for p in prices} == {"DummyJSON", "FakeStore"}
    assert {p["price"] for p in prices} == {"12.9900", "15.9900"}


async def test_price_history_has_series_per_shop(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{PRODUCT_1_ID}/price-history")
    assert resp.status_code == 200
    body = resp.json()
    assert {s["shop_name"] for s in body["series"]} == {"DummyJSON", "FakeStore"}
    assert len(body["average"]) >= 1


async def test_conversion_to_uah(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{PRODUCT_1_ID}?currency=UAH")
    assert resp.status_code == 200
    d = resp.json()
    assert d["currency"] == "UAH"
    expected = (Decimal("12.99") * USD_RATE).quantize(Decimal("0.0001"))
    assert d["price_min"] == str(expected)


async def test_bad_currency_returns_422(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{PRODUCT_1_ID}?currency=XXX")
    assert resp.status_code == 422


async def test_bad_sort_returns_422(auth_client):
    resp = await auth_client.get("/api/v1/products?sort=banana")
    assert resp.status_code == 422


async def test_requires_auth(client):
    resp = await client.get(f"/api/v1/products/{PRODUCT_1_ID}")
    assert resp.status_code == 401
