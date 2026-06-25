"""API-тесты watchlist: добавление, список, удаление, конфликты."""

import uuid

from tests.conftest import PRODUCT_1_ID, PRODUCT_2_ID


async def test_add_product_then_appears_in_list(auth_client):
    # стартово отслеживается только product 1
    assert (await auth_client.get("/api/v1/products")).json()["total"] == 1

    resp = await auth_client.post(
        "/api/v1/me/products", json={"product_id": str(PRODUCT_2_ID)}
    )
    assert resp.status_code == 201
    assert resp.json() == {"product_id": str(PRODUCT_2_ID)}

    assert (await auth_client.get("/api/v1/products")).json()["total"] == 2


async def test_add_duplicate_returns_409(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/products", json={"product_id": str(PRODUCT_1_ID)}
    )
    assert resp.status_code == 409


async def test_add_nonexistent_product_returns_404(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/products", json={"product_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


async def test_remove_tracked_product(auth_client):
    resp = await auth_client.delete(f"/api/v1/me/products/{PRODUCT_1_ID}")
    assert resp.status_code == 204
    assert (await auth_client.get("/api/v1/products")).json()["total"] == 0


async def test_remove_not_tracked_returns_404(auth_client):
    # product 2 не в watchlist
    resp = await auth_client.delete(f"/api/v1/me/products/{PRODUCT_2_ID}")
    assert resp.status_code == 404


async def test_me_products_lists_tracked(auth_client):
    resp = await auth_client.get("/api/v1/me/products")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == str(PRODUCT_1_ID)
