"""Unit tests for get_with_retry: retries on 429/5xx/transient, success after a retry,
and the error raised after all tries are used. Sleep between tries is mocked."""

import httpx
import pytest

from app.core.http_retry import get_with_retry

_REQUEST = httpx.Request("GET", "https://example.test/x")


class _Resp:
    def __init__(self, status_code: int, json_data=None) -> None:
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=_REQUEST, response=httpx.Response(self.status_code)
            )


class _Client:
    """Returns responses/exceptions from a given sequence, one per get."""

    def __init__(self, outcomes: list) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    async def get(self, url: str):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _noop(_seconds):
        return None

    monkeypatch.setattr("app.core.http_retry.asyncio.sleep", _noop)


async def test_returns_immediately_on_success():
    client = _Client([_Resp(200, {"ok": True})])
    resp = await get_with_retry(client, "u", attempts=3)
    assert resp.json() == {"ok": True}
    assert client.calls == 1


async def test_retries_on_429_then_succeeds():
    client = _Client([_Resp(429), _Resp(200, {"ok": True})])
    resp = await get_with_retry(client, "u", attempts=3)
    assert resp.status_code == 200
    assert client.calls == 2


async def test_retries_on_5xx_then_succeeds():
    client = _Client([_Resp(503), _Resp(500), _Resp(200)])
    resp = await get_with_retry(client, "u", attempts=3)
    assert resp.status_code == 200
    assert client.calls == 3


async def test_retries_on_transport_error_then_succeeds():
    client = _Client([httpx.ConnectError("boom"), _Resp(200)])
    resp = await get_with_retry(client, "u", attempts=3)
    assert resp.status_code == 200
    assert client.calls == 2


async def test_raises_http_status_error_after_exhausting_on_429():
    client = _Client([_Resp(429), _Resp(429), _Resp(429)])
    with pytest.raises(httpx.HTTPStatusError):
        await get_with_retry(client, "u", attempts=3)
    assert client.calls == 3


async def test_raises_transport_error_after_exhausting():
    client = _Client([httpx.ConnectError("a"), httpx.ConnectError("b")])
    with pytest.raises(httpx.ConnectError):
        await get_with_retry(client, "u", attempts=2)
    assert client.calls == 2


async def test_4xx_other_than_429_is_not_retried():
    client = _Client([_Resp(404)])
    with pytest.raises(httpx.HTTPStatusError):
        await get_with_retry(client, "u", attempts=3)
    assert client.calls == 1  # 404 is not retried
