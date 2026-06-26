"""Shared helper for robust HTTP GET to external APIs (shops, NBU).

External services can answer with 429 (rate limit), 5xx, or just time out. We retry
the request with exponential backoff; the number of tries comes from the settings
(`SHOP_API_RETRY_ATTEMPTS`). The logic lives here so we do not repeat the retry loop
in every adapter and in CurrencyService.
"""

import asyncio

import httpx

from app.core.logger import get_logger

logger = get_logger(__name__)


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
) -> httpx.Response:
    """GET with retries on 429, 5xx, and transient errors (timeout, dropped link).

    Between tries it waits `base_delay * 2**(n-1)` seconds. Returns a good response
    (2xx/3xx/4xx except 429). When all tries are used up it raises `HTTPStatusError`
    (for 429/5xx) or the last transport error.
    """
    last_response: httpx.Response | None = None
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(url)
        except httpx.TransportError as exc:
            last_exc = exc
            last_response = None
            logger.warning(
                f"GET {url} failed ({exc!r}) | attempt={attempt}/{attempts}"
            )
        else:
            if resp.status_code != 429 and resp.status_code < 500:
                resp.raise_for_status()
                return resp
            last_response = resp
            last_exc = None
            logger.warning(
                f"GET {url} -> {resp.status_code} | attempt={attempt}/{attempts}"
            )

        if attempt < attempts:
            await asyncio.sleep(base_delay * 2 ** (attempt - 1))

    if last_response is not None:
        last_response.raise_for_status()  # 429/5xx -> HTTPStatusError
        return last_response
    raise last_exc  # type: ignore[misc]  # we get here only if there was an exc
