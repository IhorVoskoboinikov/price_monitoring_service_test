"""Общие константы тестовых данных (детерминированные UUID).

Лёгкий модуль без инфраструктуры: импортируется и unit-, и integration-тестами,
поэтому НЕ тянет testcontainers/app — `pytest tests/unit` не поднимает Docker.
Вся БД/контейнер/клиент/фикстуры — в tests/integration/conftest.py.
"""

import uuid

DEMO_USER_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
PRODUCT_1_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")  # в watchlist, 2 магазина
PRODUCT_2_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")  # не в watchlist, 1 магазин
