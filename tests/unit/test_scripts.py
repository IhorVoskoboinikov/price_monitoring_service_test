"""Unit tests for the helper scripts in scripts/ (no DB, no network).

These guard the two bugs found earlier: a wrong db_service method name in
sync_historical_rates, and the import of the full app config in generate_token.
"""

import contextlib
import importlib

import pytest
from jose import jwt

from app.schemas.auth import TokenPayload


@pytest.mark.parametrize(
    "module",
    [
        "scripts.generate_token",
        "scripts.sync_historical_rates",
        "scripts.run_check_alerts",
    ],
)
def test_script_imports(module):
    """Each script must import cleanly (catches import-time breakage)."""
    assert importlib.import_module(module) is not None


def test_generate_token_makes_valid_payload():
    """The token must carry the demo user_id and pass the API's TokenPayload check."""
    from scripts.generate_token import DEMO_USER_ID, make_token

    token = make_token("unit-secret").removeprefix("Bearer ")
    raw = jwt.decode(token, "unit-secret", algorithms=["HS256"])

    payload = TokenPayload.model_validate(raw)  # same validation the API does
    assert str(payload.user_id) == DEMO_USER_ID


async def test_sync_historical_rates_uses_db_session(monkeypatch):
    """Regression: the script must call db_service.session() (not create_session)."""
    from scripts import sync_historical_rates as mod

    class _FakeDB:
        async def commit(self) -> None:
            pass

    @contextlib.asynccontextmanager
    async def _fake_session():
        yield _FakeDB()

    class _FakeCurrency:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def sync_historical_rates(self, date_from, date_to) -> int:
            return 7

    monkeypatch.setattr(mod.db_service, "session", _fake_session)
    monkeypatch.setattr(mod, "CurrencyService", _FakeCurrency)

    assert await mod._run(1) == 7
