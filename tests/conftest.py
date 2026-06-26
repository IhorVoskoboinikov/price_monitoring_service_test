"""Shared test data constants (deterministic UUIDs).

A light module with no infrastructure: imported by both unit and integration tests,
so it does NOT pull in testcontainers/app — `pytest tests/unit` does not start Docker.
All DB/container/client/fixtures live in tests/integration/conftest.py.
"""

import uuid

DEMO_USER_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
PRODUCT_1_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")  # in watchlist, 2 shops
PRODUCT_2_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")  # not in watchlist, 1 shop
