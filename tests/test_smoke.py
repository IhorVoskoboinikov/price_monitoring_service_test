"""Smoke-тесты: проверяют, что тестовая инфраструктура поднимается корректно."""

from sqlalchemy import func, select

from app.db.models.product import Product
from tests.conftest import PRODUCT_1_ID


async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_seed_data_present(db):
    count = await db.scalar(select(func.count(Product.id)))
    assert count == 2
    titles = (await db.execute(select(Product.title).order_by(Product.title))).scalars().all()
    assert titles == ["Test Product 1", "Test Product 2"]


async def test_auth_required(client):
    resp = await client.get("/api/v1/products")
    assert resp.status_code == 401


async def test_auth_client_ok(auth_client):
    resp = await auth_client.get(f"/api/v1/products/{PRODUCT_1_ID}")
    assert resp.status_code == 200
