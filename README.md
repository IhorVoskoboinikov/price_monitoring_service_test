# Price Tracker Service

A FastAPI backend service for tracking product price changes across several
shops (DummyJSON, FakeStore), with price history, currency conversion using NBU
rates, and email alerts when a price drops below a threshold.

Test assignment (Middle+ / Senior Python Developer). A detailed architecture
description is in [`price_tracker_architecture.md`](price_tracker_architecture.md).

## Features

- List of watched products with a price range and a trend (up/down/same vs the
  30-day average), sorted by price and by trend.
- Product card: description, price range, number of shops.
- All shop prices for today and a daily price history (one series per shop +
  the average), with each point converted using the rate of its own date.
- User watchlist (add/remove/list).
- Alerts: email when a price drops below a given threshold (threshold in any
  currency, stored in USD).
- Currency choice (`USD`/`UAH`/`EUR`/`GBP`) everywhere prices are returned.

## Tech stack

Python 3.12 · FastAPI · SQLAlchemy 2 (async) + Alembic · PostgreSQL 16
(partitioned price history) · Redis (rate cache) · Celery + Beat · httpx ·
Pydantic v2 · uv · Docker Compose.

## Architecture (short)

```
API (FastAPI)  ->  Services (business logic)  ->  Repositories  ->  PostgreSQL
                     CurrencyService  ->  Redis / NBU API
                     ShopAdapters     ->  DummyJSON / FakeStore
Celery Beat  ->  tasks (collect prices, check alerts, sync rates, partitions)
```

- **Repository-per-entity + DI**: endpoints get services through `Depends`
  (`app/api/deps.py`), services get repositories. The per-request transaction is
  opened in `_get_db` (commit on success, rollback on error).
- **Shop adapters** are isolated behind `BaseShopAdapter`; a new shop is a new
  class + one line in the registry, and the business logic does not change.
- **Prices are stored only in USD**; conversion happens on the fly through
  `ExchangeRate` (the hryvnia is the base currency).

## Quick start (Docker Compose)

```bash
# 1. Config (the only required step)
cp .env.example .env
# edit .env: at least APP_SECRET_KEY.
# For real email delivery — EMAIL_ENABLED=true and working SMTP_* (see below).

# 2. Bring up the whole stack with one command
docker compose up -d --build

# 3. Watch the startup and the automatic seed
docker compose logs -f api
```

`docker compose` builds the order by itself: `postgres`/`redis` (healthcheck) →
`migrate` (`alembic upgrade head`, we wait for a clean finish via
`depends_on: condition: service_completed_successfully`) → `api`/`worker` →
`beat`. You do not need to bring up the infrastructure and run migrations
separately.

API: <http://localhost:8000>, Swagger: <http://localhost:8000/docs>.

> On startup `api` fills the DB through the FastAPI lifespan (shops, products
> from both APIs, today's rates). The steps are idempotent: shops/products are
> created once, rates are synced on every start.
>
> You can also run migrations on their own if you want (for example, in CI):
> `docker compose run --rm migrate`.

## Authorization

All endpoints require a Bearer JWT (a static token — full auth is outside the
scope). Generate a token for the demo user:

```bash
uv run python scripts/generate_token.py
# Bearer eyJhbGciOiJIUzI1NiI...
```

Paste it into Swagger ("Authorize") or into the header:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/products
```

## Main endpoints

| Method + URL | Purpose |
|---|---|
| `GET /api/v1/products?currency=&sort=` | List of watched products with a trend |
| `GET /api/v1/products/{id}?currency=` | Product card |
| `GET /api/v1/products/{id}/prices` | Shop prices for today |
| `GET /api/v1/products/{id}/price-history` | Price history (series + average) |
| `GET/POST /api/v1/me/products` · `DELETE /api/v1/me/products/{id}` | Watchlist |
| `GET/POST /api/v1/me/alerts` · `DELETE /api/v1/me/alerts/{id}` | Alerts |
| `GET /api/v1/currencies` | Current currency rates |
| `GET /api/v1/health` | Health check |

## Email notifications

By default `EMAIL_ENABLED=false` — **console mode**: emails are not sent, they
are logged (handy for development and for checking the alert logic). For real
delivery set `EMAIL_ENABLED=true` and working `SMTP_*` in `.env` (a Gmail App
Password or Mailtrap — see the comments in `.env.example`).

## Currency rates

The source is the official NBU API (free, no key). `get_rate` follows the chain
Redis → PostgreSQL → NBU (on-demand, with a write to the DB) → nearest earlier
rate (fallback). Today's rates are synced by a Celery task; historical ones can
be loaded by hand:

```bash
uv run python scripts/sync_historical_rates.py 30   # for the last 30 days
```

## Tests

The suite is split by the levels of the test pyramid:

- **`tests/unit/`** — pure logic (trend, sorting, retries, adapter parsing with a
  mock `httpx`). No DB, no network — **no Docker needed**, runs in a fraction of
  a second. The kind you run on every commit in CI.
- **`tests/integration/`** — API endpoints and services on a real PostgreSQL in
  Docker via `testcontainers` (the same dialect as in prod — UUID, on-conflict
  upsert, window functions, and partitioning are tested for real). Redis is
  mocked with `fakeredis`, and external APIs (NBU, shops) with a fake httpx
  client.

The heavy fixtures (container, DB seeding) live in
`tests/integration/conftest.py`, so the unit suite does not pick them up.

```bash
uv run python tests/run.py              # whole suite + coverage report
uv run python tests/run.py unit         # unit only — no Docker, instant
uv run python tests/run.py integration  # integration only (testcontainers)
uv run python tests/run.py -k alert     # filter by name
```

`tests/run.py` runs pytest with coverage (term + HTML in `tests/htmlcov`).
For `integration`/the full suite you need a running Docker.

## Local development

```bash
uv sync                      # install dependencies (including dev)
uv run ruff check app/       # lint
uv run alembic upgrade head  # migrations
```

## Configuration

All settings are in `.env` (read through `pydantic-settings`, validated at
startup). A template with all variables and comments is in `.env.example`. The
real `.env` is in `.gitignore` and does not get into the repository.

## Notes on decisions

- **Mapping products between shops** — by index at seed time (the first ~20
  products get prices from two shops). In production this is replaced by
  fuzzy-matching without changing the DB schema.
- **Price dedup** — a repeated price snapshot for a product within 1 hour is not
  written.
- **Historical 5-year rate load** — moved to a script
  (`sync_historical_rates.py`) so it does not delay startup; if needed it is easy
  to turn into a background task on first run.

## Development process

The work followed GitFlow: `main` is the release branch (starting from the
initial commit), all progress went into `develop` and was merged into `main`
through a reviewed Pull Request (`develop → main`). This way the history clearly
shows step-by-step development, not one big "dump" commit.
