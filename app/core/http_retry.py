"""Общий помощник для устойчивых HTTP-GET к внешним API (магазины, НБУ).

Внешние сервисы могут отвечать 429 (rate limit), 5xx или вовсе отваливаться по
таймауту. Повторяем запрос с экспоненциальным backoff, число попыток — из
настроек (`SHOP_API_RETRY_ATTEMPTS`). Логика вынесена сюда, чтобы не дублировать
цикл ретраев в каждом адаптере и в CurrencyService.
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
    """GET с ретраями на 429, 5xx и transient-ошибках (таймаут, обрыв связи).

    Между попытками ждёт `base_delay * 2**(n-1)` секунд. Возвращает успешный
    ответ (2xx/3xx/4xx кроме 429). После исчерпания попыток пробрасывает
    `HTTPStatusError` (для 429/5xx) или последнюю transport-ошибку.
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
        last_response.raise_for_status()  # 429/5xx → HTTPStatusError
        return last_response
    raise last_exc  # type: ignore[misc]  # сюда попадаем только если был exc
