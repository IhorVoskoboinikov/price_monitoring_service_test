"""Smoke-тесты: проверяют, что тестовая инфраструктура поднимается корректно."""

from jose import jwt
from sqlalchemy import func, select

from app.core.config import settings
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


async def test_token_without_user_id_rejected(client):
    # Валидная подпись, но нет обязательного клейма user_id → TokenPayload не пройдёт
    token = jwt.encode(
        {"sub": "admin", "role": "admin"}, settings.app_secret_key, algorithm="HS256"
    )
    resp = await client.get(
        "/api/v1/products", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401
