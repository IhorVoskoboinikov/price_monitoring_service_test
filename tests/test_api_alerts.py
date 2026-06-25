"""API-тесты алертов: CRUD, валидация порога, конвертация валюты порога и
сквозной прогон check_alerts (срабатывание + деактивация + отправка email)."""

import uuid
from decimal import Decimal

import fakeredis.aioredis

from app.db.models.price_alert import PriceAlert
from app.db.repositories.alert_repo import AlertRepo
from app.db.repositories.exchange_rate_repo import ExchangeRateRepo
from app.db.repositories.product_repo import ProductRepo
from app.services.alert_service import AlertService
from app.services.currency_service import CurrencyService
from tests.conftest import DEMO_USER_ID, PRODUCT_1_ID

USD_RATE = Decimal("44.8685")


# ── CRUD ──────────────────────────────────────────────────────────────────────


async def test_create_alert_then_listed(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/alerts",
        json={"product_id": str(PRODUCT_1_ID), "threshold_price": "10.00"},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["product_id"] == str(PRODUCT_1_ID)
    assert created["threshold_price_usd"] == "10.0000"
    assert created["currency_code"] == "USD"
    assert created["is_active"] is True

    listed = (await auth_client.get("/api/v1/me/alerts")).json()["items"]
    assert [a["id"] for a in listed] == [created["id"]]


async def test_create_alert_uah_threshold_converted_to_usd(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/alerts",
        json={
            "product_id": str(PRODUCT_1_ID),
            "threshold_price": "5000",
            "currency": "UAH",
        },
    )
    assert resp.status_code == 201
    # USD = 5000 UAH * rate_uah(=1) / rate_usd
    expected = (Decimal("5000") * Decimal(1) / USD_RATE).quantize(Decimal("0.0001"))
    assert resp.json()["threshold_price_usd"] == str(expected)
    assert resp.json()["currency_code"] == "UAH"


async def test_delete_alert(auth_client):
    alert_id = (
        await auth_client.post(
            "/api/v1/me/alerts",
            json={"product_id": str(PRODUCT_1_ID), "threshold_price": "10.00"},
        )
    ).json()["id"]

    resp = await auth_client.delete(f"/api/v1/me/alerts/{alert_id}")
    assert resp.status_code == 204
    assert (await auth_client.get("/api/v1/me/alerts")).json()["items"] == []


# ── Валидация ─────────────────────────────────────────────────────────────────


async def test_threshold_must_be_positive(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/alerts",
        json={"product_id": str(PRODUCT_1_ID), "threshold_price": "0"},
    )
    assert resp.status_code == 422


async def test_extra_field_rejected(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/alerts",
        json={
            "product_id": str(PRODUCT_1_ID),
            "threshold_price": "10.00",
            "hacker": "x",
        },
    )
    assert resp.status_code == 422


async def test_create_alert_nonexistent_product_404(auth_client):
    resp = await auth_client.post(
        "/api/v1/me/alerts",
        json={"product_id": str(uuid.uuid4()), "threshold_price": "10.00"},
    )
    assert resp.status_code == 404


async def test_delete_nonexistent_alert_404(auth_client):
    resp = await auth_client.delete(f"/api/v1/me/alerts/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_alerts_require_auth(client):
    resp = await client.get("/api/v1/me/alerts")
    assert resp.status_code == 401


# ── Сквозной прогон check_alerts ──────────────────────────────────────────────


async def test_check_alerts_triggers_and_deactivates(db, monkeypatch):
    """Порог выше текущей минимальной цены → алерт срабатывает: письмо уходит,
    is_active становится False, повторный прогон уже ничего не шлёт."""
    sent: list[tuple[str, str, str]] = []

    async def fake_send_email(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    monkeypatch.setattr(
        "app.services.alert_service.send_email", fake_send_email
    )

    alert_id = uuid.uuid4()
    db.add(
        PriceAlert(
            id=alert_id,
            user_id=DEMO_USER_ID,
            product_id=PRODUCT_1_ID,  # минимальная текущая цена 12.99 USD
            threshold_price_usd=Decimal("9999"),
            currency_code="USD",
            is_active=True,
        )
    )
    await db.commit()

    service = AlertService(
        AlertRepo(db),
        ProductRepo(db),
        CurrencyService(
            ExchangeRateRepo(db),
            fakeredis.aioredis.FakeRedis(decode_responses=True),
        ),
    )

    sent_count = await service.check_alerts()
    await db.commit()

    assert sent_count == 1
    assert len(sent) == 1
    assert sent[0][0] == "demo@example.com"

    refreshed = await db.get(PriceAlert, alert_id)
    await db.refresh(refreshed)
    assert refreshed.is_active is False
    assert refreshed.triggered_at is not None

    # повторный прогон — алерт уже неактивен, писем больше нет
    assert await service.check_alerts() == 0
    assert len(sent) == 1
