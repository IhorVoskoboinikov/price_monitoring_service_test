"""An unexpected error is turned into a consistent 500 JSON envelope.

The global `Exception` handler must answer with the same `{"detail": ...}` shape
as the domain errors, not a plain-text "Internal Server Error". Starlette
re-raises after the 500 handler runs, so the client transport is built with
`raise_app_exceptions=False` to observe the response instead of the exception.
"""

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.currency_service import CurrencyService


async def test_unhandled_error_returns_json_500(auth_headers, monkeypatch):
    async def boom(self):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(CurrencyService, "get_today_rates", boom)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=auth_headers
    ) as c:
        resp = await c.get("/api/v1/currencies")

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error"}
