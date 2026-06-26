"""Pytest fixtures for integration tests: a test Postgres (testcontainers),
a clean + seeded DB per test, an async httpx client, and authorization.

The DB is a real Postgres in a container (the same dialect as prod): UUID,
on-conflict upsert, window functions, and partitioning are tested for real.
These fixtures (and the autouse DB seeding) work ONLY in tests/integration/ —
unit tests in tests/unit/ do not pick them up and do not start Docker.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from decimal import Decimal

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

# Importing app pulls in all models -> Base.metadata is filled.
from app.api.deps import _get_db
from app.core.config import settings
from app.db.models.base import Base
from app.db.models.exchange_rate import ExchangeRate
from app.db.models.price_history import PriceHistory
from app.db.models.product import Product
from app.db.models.product_shop import ProductShop
from app.db.models.shop import Shop
from app.db.models.user import User
from app.db.models.user_product import UserProduct
from app.main import app
from tests.conftest import DEMO_USER_ID, PRODUCT_1_ID, PRODUCT_2_ID

__all__ = ["DEMO_USER_ID", "PRODUCT_1_ID", "PRODUCT_2_ID"]


# ── Infrastructure: container, engine, schema ─────────────────────────────────


@pytest.fixture(scope="session")
def _postgres_container():
    """Start Postgres and create the schema once with a sync engine.

    We create the schema with a sync driver (psycopg2) so the DDL is not tied to an
    event loop — then all async work (engine/sessions/tests) lives in one test loop.
    """
    with PostgresContainer("postgres:16-alpine") as pg:
        sync_engine = create_engine(pg.get_connection_url())
        with sync_engine.begin() as conn:
            Base.metadata.create_all(conn)
            # price_history is partitioned -> we need a partition, or INSERT fails.
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS price_history_default "
                    "PARTITION OF price_history DEFAULT"
                )
            )
        sync_engine.dispose()
        yield pg


@pytest.fixture(scope="session")
def _database_url(_postgres_container) -> str:
    # testcontainers gives a URL with a sync driver — switch it to asyncpg.
    return _postgres_container.get_connection_url().replace("psycopg2", "asyncpg")


@pytest_asyncio.fixture
async def test_engine(_database_url):
    engine = create_async_engine(_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def test_sessionmaker(test_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(test_engine, expire_on_commit=False, autoflush=False)


# ── Swap external deps: Redis → fakeredis, _get_db → test session ─────────────


@pytest.fixture(scope="session", autouse=True)
def _patch_redis():
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    import app.api.deps as deps_mod
    import app.core.redis as redis_mod

    deps_mod.redis_client = fake
    redis_mod.redis_client = fake
    yield


@pytest.fixture(autouse=True)
def _override_get_db(test_sessionmaker):
    async def override() -> AsyncGenerator[AsyncSession, None]:
        async with test_sessionmaker() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[_get_db] = override
    yield
    app.dependency_overrides.pop(_get_db, None)


# ── Clean + seeded DB per test ────────────────────────────────────────────────


async def _seed(session: AsyncSession) -> None:
    """A deterministic data set with no calls to external APIs."""
    shop1 = Shop(name="DummyJSON", base_url="https://dummyjson.com",
                 adapter_key="dummyjson", is_active=True)
    shop2 = Shop(name="FakeStore", base_url="https://fakestoreapi.com",
                 adapter_key="fakestore", is_active=True)
    session.add_all([shop1, shop2])
    await session.flush()

    session.add(User(id=DEMO_USER_ID, email="demo@example.com", is_active=True))

    p1 = Product(id=PRODUCT_1_ID, title="Test Product 1", description="Desc 1",
                 category="beauty", description_source_shop_id=shop1.id)
    p2 = Product(id=PRODUCT_2_ID, title="Test Product 2", description="Desc 2",
                 category="tech", description_source_shop_id=shop1.id)
    session.add_all([p1, p2])
    await session.flush()

    ps1a = ProductShop(product_id=p1.id, shop_id=shop1.id, external_id="1")
    ps1b = ProductShop(product_id=p1.id, shop_id=shop2.id, external_id="101")
    ps2 = ProductShop(product_id=p2.id, shop_id=shop1.id, external_id="2")
    session.add_all([ps1a, ps1b, ps2])
    await session.flush()

    now = datetime.now(timezone.utc)
    session.add_all([
        PriceHistory(product_shop_id=ps1a.id, price_usd=Decimal("12.99"), recorded_at=now),
        PriceHistory(product_shop_id=ps1b.id, price_usd=Decimal("15.99"), recorded_at=now),
        PriceHistory(product_shop_id=ps2.id, price_usd=Decimal("50.00"), recorded_at=now),
    ])

    today = now.date()
    session.add_all([
        ExchangeRate(currency_code="USD", rate_uah_per_unit=Decimal("44.8685"), date=today, source="TEST"),
        ExchangeRate(currency_code="EUR", rate_uah_per_unit=Decimal("50.8809"), date=today, source="TEST"),
        ExchangeRate(currency_code="GBP", rate_uah_per_unit=Decimal("59.0559"), date=today, source="TEST"),
    ])

    # the demo user watches only product 1
    session.add(UserProduct(user_id=DEMO_USER_ID, product_id=PRODUCT_1_ID))


@pytest_asyncio.fixture(autouse=True)
async def _clean_and_seed(test_engine, test_sessionmaker):
    table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with test_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    async with test_sessionmaker() as session:
        await _seed(session)
        await session.commit()
    yield


# ── Client and authorization ──────────────────────────────────────────────────


@pytest.fixture
def auth_headers() -> dict[str, str]:
    token = jwt.encode(
        {"sub": "admin", "role": "admin", "user_id": str(DEMO_USER_ID)},
        settings.app_secret_key,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Client without authorization."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_client(auth_headers) -> AsyncGenerator[AsyncClient, None]:
    """Client with the demo user's Bearer token for protected endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=auth_headers
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db(test_sessionmaker) -> AsyncGenerator[AsyncSession, None]:
    """Direct access to the test DB (to prepare data and check things in tests)."""
    async with test_sessionmaker() as session:
        yield session
