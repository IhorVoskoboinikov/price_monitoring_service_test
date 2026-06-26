"""API tests for the catalog: list all products, pagination, conversion, auth."""

from decimal import Decimal

from tests.conftest import PRODUCT_1_ID, PRODUCT_2_ID

USD_RATE = Decimal("44.8685")


async def test_catalog_lists_all_products(auth_client):
    resp = await auth_client.get("/api/v1/catalog")
    assert resp.status_code == 200
    body = resp.json()
    # seed has 2 products (catalog is global, not the watchlist)
    assert body["total"] == 2
    ids = {item["id"] for item in body["items"]}
    assert ids == {str(PRODUCT_1_ID), str(PRODUCT_2_ID)}


async def test_catalog_shows_price_range_and_shops(auth_client):
    resp = await auth_client.get("/api/v1/catalog")
    by_id = {item["id"]: item for item in resp.json()["items"]}
    p1 = by_id[str(PRODUCT_1_ID)]
    assert p1["price_min"] == "12.9900"
    assert p1["price_max"] == "15.9900"
    assert p1["shops_count"] == 2


async def test_catalog_paginates(auth_client):
    resp = await auth_client.get("/api/v1/catalog?page=1&page_size=1")
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["page_size"] == 1


async def test_catalog_converts_currency(auth_client):
    resp = await auth_client.get("/api/v1/catalog?currency=UAH")
    by_id = {item["id"]: item for item in resp.json()["items"]}
    p2 = by_id[str(PRODUCT_2_ID)]
    expected = (Decimal("50.00") * USD_RATE).quantize(Decimal("0.0001"))
    assert p2["currency"] == "UAH"
    assert p2["price_min"] == str(expected)


async def test_catalog_requires_auth(client):
    resp = await client.get("/api/v1/catalog")
    assert resp.status_code == 401
