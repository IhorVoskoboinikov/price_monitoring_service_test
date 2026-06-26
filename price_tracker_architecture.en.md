# Architecture document
## Product price tracking service
**Price Tracker Service — v1.0**
*Test assignment: Middle+ / Senior Python Developer*

---

## Table of contents

1. [System overview](#1-system-overview)
2. [Tech stack and rationale](#2-tech-stack-and-rationale)
3. [Database models](#3-database-models)
4. [API endpoints](#4-api-endpoints)
5. [Service and class architecture](#5-service-and-class-architecture)
6. [Background tasks (Celery)](#6-background-tasks-celery)
7. [Scaling](#7-scaling)
8. [Currency module — NBU API](#8-currency-module--nbu-api)
9. [Project structure](#9-project-structure)
10. ["To be clarified" decisions](#10-to-be-clarified-decisions)
11. [Sequence: price collection](#11-sequence-price-collection)
12. [Configuration and authorization](#12-app-configuration)
13. [Running with Docker Compose](#13-running-with-docker-compose)

---

## 1. System overview

Price Tracker is a Python backend service that collects product prices from external shop APIs, stores history, converts prices into the requested currency, and notifies users about price changes.

### 1.1 Key requirements

- A user registers with email + password (auth is out of scope of the assignment).
- A user builds a list of products to track.
- The service periodically polls the APIs: `dummyjson.com/products` and `fakestoreapi.com/products`.
- Prices are stored with history (unlimited in time).
- Current and historical NBU (Ukraine) currency rates are supported.
- The API provides a product list with a trend, a product page, and price history.
- An email alert when a price drops below a given threshold.

### 1.2 Context diagram (C4 Level 1)

| Actor / System | Role |
|---|---|
| User | Registers, sets up a list, views prices and trends |
| Price Tracker API | The main system: stores data, provides a REST API |
| DummyJSON API | External source of products and prices (`dummyjson.com`) |
| FakeStore API | External source of products and prices (`fakestoreapi.com`) |
| NBU API | Ukraine currency rates — `bank.gov.ua/NBUStatService` |
| Email provider | SMTP / SendGrid — delivery of price-change notifications |

---

## 2. Tech stack and rationale

| Technology | Why it was chosen |
|---|---|
| Python 3.12 | Stable, good async support, a rich web ecosystem |
| FastAPI | Native async, OpenAPI auto-generation, Pydantic v2 out of the box, high performance vs Django REST |
| PostgreSQL 16 | ACID, table partitioning (`PARTITION BY RANGE` for price history), good JSON operators |
| SQLAlchemy 2.x + Alembic | An ORM with async support (`AsyncSession`, `AsyncEngine`), Alembic for migrations — the Python standard |
| Redis 7 | Cache for currency rates and aggregated prices (TTL), broker for Celery |
| Celery + Celery Beat | Periodic tasks (price collection, alert checks, rate updates). Beat = a cron replacement without a cronjob |
| Pydantic v2 | Request/response schemas, validation, serialization. v2 is 5–20x faster than v1 |
| httpx | Async HTTP client for requests to external shop APIs and the NBU |
| UV | Package manager — replaces pip + virtualenv + pip-tools. Lock file, dev/prod dependency split, 10–100x faster installs than pip in Docker |
| NBU API | `bank.gov.ua/NBUStatService` — free, official, supports history |

> **Why not Django:** FastAPI + SQLAlchemy give cleaner async without the overhead of the Django ORM. For an API-only service with no templates, Django is overkill.

> **Why UV and not requirements.txt:** `requirements.txt` does not pin transitive dependencies without `pip-compile`, does not split dev/prod, and installs slowly in Docker. UV solves all three: `uv.lock` is an exact snapshot of the whole dependency tree, and `uv sync --frozen --no-dev` in Docker installs only prod dependencies from the lock file in seconds.

> **Why the NBU API:** an official source, free, and it provides historical rates by date (`GET /NBUStatService/v1/statdirectory/exchange?valcode=USD&date=YYYYMMDD&json`). Alternatives — `exchangerate.host` or `openexchangerates.org` — are either paid or less reliable for UAH.

---

## 3. Database models

### 3.1 User

A user of the system. Full auth is out of scope of the assignment — a static JWT is used (see section 12.4). The `password_hash` field is reserved for the future: in the current version registration/login are not implemented, so it is not filled.

| Field | Type / description |
|---|---|
| `id` | UUID, PK, `default gen_random_uuid()` |
| `email` | VARCHAR(255), UNIQUE NOT NULL |
| `password_hash` | VARCHAR(255) NOT NULL — bcrypt hash (reserved, see above) |
| `is_active` | BOOLEAN, default TRUE |
| `created_at` | TIMESTAMPTZ, default NOW() |

### 3.2 Shop

A shop — a source of prices. The adapter pattern is bound to the `adapter_key` field.

| Field | Type / description |
|---|---|
| `id` | SERIAL, PK |
| `name` | VARCHAR(100) NOT NULL — `'DummyJSON'`, `'FakeStore'` |
| `base_url` | VARCHAR(255) — the API base URL |
| `adapter_key` | VARCHAR(50) UNIQUE — key for the adapter factory (`'dummyjson'`, `'fakestore'`) |
| `is_active` | BOOLEAN — whether the shop is included in polling |

### 3.3 Product

A product — a logical entity, not bound to a specific shop.

| Field | Type / description |
|---|---|
| `id` | UUID, PK |
| `title` | VARCHAR(500) NOT NULL |
| `description` | TEXT |
| `category` | VARCHAR(200) |
| `description_source_shop_id` | INT, FK → `Shop.id`, nullable — which shop the description was taken from |
| `created_at` | TIMESTAMPTZ |

> **Choosing the description (the assignment requirement "the description can be taken from any API"):** one product can be present in several shops with different descriptions. The rule for the current version — the description is taken from the shop with the lowest `shop_id` priority (effectively the first shop where the product appeared during seed), and is fixed in `description_source_shop_id`. This makes the choice deterministic and transparent. If production needs a different priority (for example, the longest or the freshest description) — only the logic that fills this field changes, the schema does not.

### 3.4 ProductShop

The link between a product and a shop. Holds the product's `external_id` in a specific shop. One product can be present in several shops with different IDs.

| Field | Type / description |
|---|---|
| `id` | SERIAL, PK |
| `product_id` | UUID, FK → `Product.id` |
| `shop_id` | INT, FK → `Shop.id` |
| `external_id` | VARCHAR(100) — the product ID in the shop's API |
| UNIQUE | `(product_id, shop_id)` |

### 3.5 PriceHistory ⭐

The main table. Stores every recorded price value from a specific shop. Partitioned by date to scale up to millions of records.

| Field | Type / description |
|---|---|
| `id` | BIGSERIAL, PK (part of the partition key) |
| `product_shop_id` | INT, FK → `ProductShop.id` |
| `price_usd` | NUMERIC(12, 4) NOT NULL — the price is always in USD |
| `recorded_at` | TIMESTAMPTZ NOT NULL — when the price was taken |
| PARTITION BY | `RANGE (recorded_at)` — by month |

> **Important:** prices are stored only in USD. Conversion to UAH/EUR/other happens on the fly through `ExchangeRate`. This avoids data duplication and lets us recompute retroactively using the historical rate.

### 3.6 ExchangeRate

A currency rate against the hryvnia on a specific date. Filled by a Celery task once a day through the NBU API. The NBU returns the rate as "how many hryvnias per 1 unit of currency" — we store it the same way for consistency (see section 8.1).

| Field | Type / description |
|---|---|
| `id` | SERIAL, PK |
| `currency_code` | CHAR(3) NOT NULL — `'USD'`, `'EUR'`, `'GBP'` |
| `rate_uah_per_unit` | NUMERIC(16, 8) NOT NULL — how many hryvnias per 1 unit of currency (for USD ≈ 41.4) |
| `date` | DATE NOT NULL |
| `source` | VARCHAR(50) — `'NBU'` |
| UNIQUE | `(currency_code, date)` |

> **The hryvnia as the base currency:** UAH is not stored as a separate row (its rate against itself = 1). USD → EUR conversion goes through the hryvnia: `price_usd * rate_usd / rate_eur`.

### 3.7 UserProduct

A user's list of products to track. A many-to-many link.

| Field | Type / description |
|---|---|
| `user_id` | UUID, FK → `User.id` |
| `product_id` | UUID, FK → `Product.id` |
| `added_at` | TIMESTAMPTZ |
| PK | `(user_id, product_id)` |

### 3.8 PriceAlert

An email alert: if a product's price drops below `threshold_price` — send an email.

| Field | Type / description |
|---|---|
| `id` | UUID, PK |
| `user_id` | UUID, FK → `User.id` |
| `product_id` | UUID, FK → `Product.id` |
| `threshold_price_usd` | NUMERIC(12, 4) — the threshold price in USD |
| `currency_code` | CHAR(3) — the currency the threshold was set in |
| `is_active` | BOOLEAN — deactivated after firing |
| `triggered_at` | TIMESTAMPTZ — when it fired |
| `created_at` | TIMESTAMPTZ |

### 3.9 Indexes

We index the specific "hot" query paths; detailed rationale and techniques (covering / partial / partition pruning / write amplification) are in section 7.5.

**Explicit indexes:**

| Index | For which query |
|---|---|
| `price_history(product_shop_id, recorded_at DESC) INCLUDE (price_usd)` | "Last shop price" and price history. Covering → index-only scan. Inherited by partitions (see 7.1) |
| `product_shops(product_id)` | JOIN product→shops during price aggregation |
| `product_shops(shop_id)` | Fetcher: links by shop (`list_product_shops(shop_id)`) |
| `price_alerts(user_id, created_at DESC)` | User's alert list (filter + sort) |
| `price_alerts(product_id) WHERE is_active` | Partial: the trigger check looks only at active alerts |
| `exchange_rates(currency_code, date)` | UNIQUE — rate lookup and `≤ date` (fallback) |

**Covered by PK / UNIQUE (no separate index needed):**

| Query | Covered by |
|---|---|
| User's watchlist (`WHERE user_id`) | PK `user_products(user_id, product_id)` — leading `user_id` |
| Rate by date/currency | UNIQUE `(currency_code, date)` |
| User by email | UNIQUE `users(email)` |
| Shop by adapter_key | UNIQUE `shops(adapter_key)` |
| Point lookups by id | primary keys |

> We deliberately do **not** index `products.description_source_shop_id` (it is never filtered on) — an extra index only makes writes more expensive.

---

## 4. API endpoints

All endpoints require authorization (Bearer JWT). The `currency` parameter (default `USD`) is supported everywhere prices are returned.

### 4.1 Products — list

```
GET /api/v1/products
```

| Parameter | Description |
|---|---|
| Query params | `currency=UAH\|USD\|EUR` (default: `USD`) |
| | `sort=price_asc\|price_desc\|trend_asc\|trend_desc` |
| | Pagination: `page` / `page_size` (offset, see 5.2) |
| Response 200 | `{ items: [ProductListItem], page, page_size, total }` |
| `ProductListItem` | `id, title, price_min, price_max, currency, trend: up\|down\|same` |
| `trend` logic | Average price today vs average over 30 days, threshold ±1% (details in section 5.2) |

### 4.2 Product — detail page

```
GET /api/v1/products/{product_id}
```

| Parameter | Description |
|---|---|
| Query params | `currency=USD` |
| Response 200 | `id, title, description, category, price_min, price_max, currency, shops_count` |
| `shops_count` | Number of shops where the product is currently available (number of `ProductShop` rows for the product). Used in the UI — show "available in N shops" |

### 4.3 All prices per shop

```
GET /api/v1/products/{product_id}/prices
```

| Parameter | Description |
|---|---|
| Query params | `currency=USD` |
| Response 200 | `{ items: [{ shop_name, price, currency, last_updated }] }` |
| Description | The latest recorded price from each shop that has the product |

### 4.4 Price history

```
GET /api/v1/products/{product_id}/price-history
```

| Parameter | Description |
|---|---|
| Query params | `currency=USD`, `date_from=YYYY-MM-DD`, `date_to=YYYY-MM-DD` |
| Response 200 | `{ series: [{ shop_name, data: [{ date, price }] }], average: [{ date, price }] }` |
| Description | Data for the chart: a series per shop + the daily average price |

> **The average over different history periods (the assignment requirement "price history in different shops can differ"):** shop A may have a price for January, while shop B has one only from March. The average for each day is computed **only over the shops that have a record on that day** — `average[date] = avg(prices of all shops that had a record on date)`. Days with no data for a shop are not counted as zero (that would distort the average), they are simply excluded from that day's computation. On the chart, a shop's line starts at its first record and ends at its last — the frontend does not connect gaps. Each point is converted into the chosen currency using the rate of its own date (see section 5.3).

### 4.5 User's product list

| Method + URL | Description |
|---|---|
| `GET /api/v1/me/products` | The current user's list of tracked products |
| `POST /api/v1/me/products` | Body: `{ product_id }`. Add a product to the list |
| `DELETE /api/v1/me/products/{product_id}` | Remove a product from tracking |

> **How a user builds the tracking list.** The assignment states that the *way* the list is created "is omitted". The boundary is taken as follows: **the catalog is filled automatically** (seed + periodic price collection from DummyJSON and FakeStore, see 5.5/5.7), and the user **marks the products they want from the catalog** into their personal watchlist by `product_id`. The user does not add an arbitrary product by URL — they choose from products the system already knows.
>
> Implementation: a many-to-many link `UserProduct(user_id, product_id)` (3.7). `POST /me/products` checks that the product exists (404 otherwise) and is not yet in the list (409 otherwise), and adds a row; `user_id` is taken from the JWT — the list is private. The product list page (4.1) already returns **only** the current user's watchlist (JOIN on `UserProduct`), not the whole catalog.

### 4.6 Alerts

| Method + URL | Description |
|---|---|
| `GET /api/v1/me/alerts` | The user's alert list |
| `POST /api/v1/me/alerts` | Body: `{ product_id, threshold_price, currency }`. Create an alert |
| `DELETE /api/v1/me/alerts/{alert_id}` | Delete an alert |

### 4.7 Utility endpoints

| Method + URL | Description |
|---|---|
| `GET /api/v1/currencies` | List of available currencies with the current rate |
| `GET /api/v1/health` | App liveness probe (`{"status": "ok"}`) |

> **Health check:** in the current version — a simple liveness probe that the process is up and responding (enough for the healthcheck in Docker Compose). A deep readiness check (DB, Redis, worker availability) is a direction for production monitoring; it is not required by the assignment.

---

## 5. Service and class architecture

### 5.0 The async principle

All services, repositories, and adapters that do I/O are implemented as **async**. This lets FastAPI handle many requests in parallel without blocking the event loop.

| Component | Async | Reason |
|---|---|---|
| FastAPI endpoints | ✅ `async def` | Native support, the entry point |
| Services (`PriceService`, `CurrencyService`, `AlertService`) | ✅ `async def` | They query the DB and Redis |
| Repositories (`ProductRepo`, `PriceRepo`) | ✅ `async def` | All queries go through async SQLAlchemy |
| Shop adapters (`DummyJsonAdapter`, `FakeStoreAdapter`) | ✅ `async def` | HTTP requests via `httpx.AsyncClient` |
| `CurrencyService.get_rate()` | ✅ `async def` | Queries to Redis and the DB, sometimes the NBU API |
| `wait_for_db.py` | ✅ `asyncio.run()` | Connection check via async SQLAlchemy |
| Celery tasks | ⚠️ sync wrapper | Celery does not support async directly — the task is synchronous and calls `asyncio.run(service.method())` inside |
| `config.py` / `Settings` | ❌ sync | Just reading variables, no I/O |
| Pydantic schemas | ❌ sync | Data validation, no I/O |

> **Celery and async:** the Celery worker runs in a synchronous context. So each task is a thin synchronous wrapper that runs an async service via `asyncio.run()`. The logic stays in the async services, the task only kicks off the run.

```python
# ✅ Correct — service is async, task is a sync wrapper
@app.task
def check_price_alerts_task():
    asyncio.run(AlertService().check_alerts())  # async inside

# ✅ Correct — repository and service are async
class PriceService:
    async def get_current_prices(self, product_id: UUID, currency: str) -> list[PriceItem]:
        rows = await self.price_repo.get_current_prices(product_id)   # async DB query
        # convert accounts for the rate direction and date (see CurrencyService)
        return [
            PriceItem(price=await self.currency_service.convert(row.price_usd, currency))
            for row in rows
        ]

# ✅ Correct — adapter is async
class DummyJsonAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        async with httpx.AsyncClient() as client:           # async HTTP
            resp = await client.get(f"{self.base_url}/products")
        return [ShopProduct(...) for p in resp.json()["products"]]
```



### 5.1 The shop adapter pattern

For extensibility the set of shops is isolated behind a single `BaseShopAdapter` interface. A new shop is a new class + registration in the registry. The business logic does not change.

#### Problem: different response shapes

Both shops return a different structure — the adapter hides this difference from the rest of the system.

**FakeStore** — returns a plain array:
```json
[
  {
    "id": 1,
    "title": "Fjallraven Backpack",
    "price": 109.95,
    "description": "Your perfect pack...",
    "category": "men's clothing",
    "image": "https://fakestoreapi.com/img/81fPKd-2AYL.png"
  }
]
```

**DummyJSON** — wraps it in an object with pagination, and has many more fields:
```json
{
  "products": [
    {
      "id": 1,
      "title": "Essence Mascara Lash Princess",
      "price": 9.99,
      "description": "Popular mascara...",
      "category": "beauty",
      "thumbnail": "https://cdn.dummyjson.com/...",
      "discountPercentage": 10.48,
      "stock": 99,
      "brand": "Essence",
      "sku": "BEA-ESS-ESS-001"
    }
  ],
  "total": 194,
  "skip": 0,
  "limit": 30
}
```

#### Solution: a single internal format

Both adapters transform their response into `ShopProduct`. Everything above — services, the DB, the business logic — works only with `ShopProduct` and knows nothing about the details of the external APIs.

```python
@dataclass
class ShopProduct:
    external_id: str
    title: str
    description: str
    category: str
    price_usd: float
    # extra fields (stock, brand, sku, discountPercentage) are simply ignored
```

```python
class BaseShopAdapter(ABC):
    @abstractmethod
    async def fetch_products(self) -> list[ShopProduct]:
        """Return the list of products with prices."""

    @abstractmethod
    async def fetch_product(self, external_id: str) -> ShopProduct | None:
        """Return a single product by ID."""


class FakeStoreAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/products")
        # FakeStore returns a plain array [...]
        return [
            ShopProduct(
                external_id=str(p["id"]),
                title=p["title"],
                description=p["description"],
                category=p["category"],
                price_usd=p["price"],
            )
            for p in resp.json()
        ]


class DummyJsonAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        # DummyJSON returns at most part of the products at a time (~194 total),
        # so we page through skip/limit until we have them all
        products: list[ShopProduct] = []
        skip, limit = 0, 100
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self.base_url}/products?limit={limit}&skip={skip}"
                )
                data = resp.json()
                # DummyJSON wraps it in {"products": [...], "total": 194, ...}
                for p in data["products"]:
                    products.append(ShopProduct(
                        external_id=str(p["id"]),
                        title=p["title"],
                        description=p["description"],
                        category=p["category"],
                        price_usd=p["price"],
                        # the other fields (stock, brand, sku...) are ignored
                    ))
                skip += limit
                if skip >= data["total"]:
                    break
        return products


ADAPTERS: dict[str, type[BaseShopAdapter]] = {
    'dummyjson': DummyJsonAdapter,
    'fakestore': FakeStoreAdapter,
}
```

> **The key principle:** an adapter knows everything about its shop and lets nothing extra leak outside. Adding a new shop with any response shape is only a new adapter class, nothing else in the system changes.

### 5.2 PriceService

The core business logic: price aggregation, trend computation, conversion.

| Method | Description |
|---|---|
| `get_products_list(user_id, currency, sort)` | The user's product list with a price range and a trend |
| `get_product_detail(product_id, currency)` | The product detail card |
| `get_current_prices(product_id, currency)` | The current price from each shop |
| `get_price_history(product_id, currency, date_from, date_to)` | Price history for the chart per shop and the average |
| `calculate_trend(product_id)` | Compares avg today vs avg over 30 days → `up`/`down`/`same` |

#### Price range and trend logic

A product can have several shops with different prices. We need to define clearly what we show:

- **`price_min` / `price_max` for today** — the minimum and maximum price across all shops that have the product, by the latest records for the current day.
- **The trend** is computed as follows: take the product's average price for today (average across all shops) and compare it with the average price over the previous 30 days (average of all records of all shops over the period). The result:
  - `up` — if `avg_today > avg_30d * 1.01`
  - `down` — if `avg_today < avg_30d * 0.99`
  - `same` — if the difference is within ±1%

```python
def determine_trend(avg_today: Decimal, avg_30d: Decimal) -> str:
    if avg_30d == 0:
        return "same"
    ratio = avg_today / avg_30d
    if ratio > Decimal("1.01"):
        return "up"
    if ratio < Decimal("0.99"):
        return "down"
    return "same"
```

> The trend is computed in USD (on the original prices) — currency conversion does not affect the trend direction, so computing it before conversion is both more correct and cheaper.

#### Sorting and pagination

The list is a specific user's watchlist; it is small (a few to a few dozen products), and the trend and price range are computed fields (aggregates over several shops). So plain `OFFSET` pagination (`page` / `page_size`) is applied over the already-aggregated and in-memory-sorted result — the same for all sort kinds. This is simple and enough for watchlist sizes.

> **Direction of growth (not required by the assignment):** if we were paging a global catalog (hundreds of thousands to millions of products) by an indexed field, then for `sort=price_*` it would make sense to switch to cursor pagination (`cursor=<last_id>`) to avoid the growing cost of `OFFSET` at large offsets. For a user's watchlist this is overkill.

### 5.3 CurrencyService

Manages currency rates. Caches in Redis (TTL for the current rate from `.env`, historical ones indefinitely).

| Method | Description |
|---|---|
| `convert(amount_usd, currency, date=None)` | Convert an amount from USD into the given currency on the needed date. `date=None` → today's rate. For historical chart points the point's date is passed |
| `get_rate(currency, date)` | Return the "hryvnias per unit of currency" rate from the cache or the DB. If missing — a request to the NBU API |
| `sync_today_rates()` | Celery task: load today's rates for all currencies from the NBU |
| `sync_historical_rates(date_from, date_to)` | A one-off load of historical rates during initialization |

> **Historical prices are converted using the rate of their own date.** In `get_price_history`, for each chart point the rate on that point's date is used, not today's. Otherwise the chart in hryvnias would distort the real dynamics. `convert()` accepts `date` exactly for this — each history point is converted via `get_rate(currency, point.date)`.

### 5.4 AlertService

Manages users' alerts.

| Method | Description |
|---|---|
| `create_alert(user_id, product_id, threshold, currency)` | Creates a `PriceAlert`. The threshold is converted into USD at the current rate and stored as `threshold_price_usd` |
| `check_alerts()` | Celery Beat, interval from `.env`. Finds active alerts where the product's minimum price (in USD) ≤ the threshold. Sends an email and deactivates |
| `send_alert_email(alert)` | Builds the email and sends it via the email provider |

### 5.5 PriceFetcherService

Coordinates price collection from the shops.

| Method | Description |
|---|---|
| `fetch_all()` | Celery Beat, interval from `.env` (default 4 hours). Runs `fetch_shop()` for each active shop |
| `fetch_shop(shop_id)` | Gets products through the adapter, writes `PriceHistory` |
| `save_price(product_shop_id, price_usd)` | Saves a price snapshot. Avoids duplicates within < 1 hour |

### 5.6 Adding a new shop

The process is fully isolated from the business logic thanks to the adapter pattern. Four steps:

**Step 1 — Implement the adapter**

```python
# app/services/shop_adapters/newshop.py
class NewShopAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        async with httpx.AsyncClient() as client:
            resp = await client.get("https://newshop.com/api/products")
        return [
            ShopProduct(external_id=str(p["id"]), title=p["name"], price_usd=p["price"])
            for p in resp.json()
        ]

    async def fetch_product(self, external_id: str) -> ShopProduct | None:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://newshop.com/api/products/{external_id}")
        if resp.status_code == 404:
            return None
        p = resp.json()
        return ShopProduct(external_id=str(p["id"]), title=p["name"], price_usd=p["price"])
```

**Step 2 — Register it in the registry**

```python
# app/services/shop_adapters/registry.py
ADAPTERS: dict[str, type[BaseShopAdapter]] = {
    'dummyjson': DummyJsonAdapter,
    'fakestore': FakeStoreAdapter,
    'newshop':   NewShopAdapter,   # <-- add a line
}
```

**Step 3 — Add a row to the DB**

```sql
INSERT INTO shop (name, base_url, adapter_key, is_active)
VALUES ('NewShop', 'https://newshop.com/api', 'newshop', true);
```

This is done via an Alembic data migration or a seed script. No app restart is needed — `fetch_all()` reads the list of shops from the DB on every task run.

**Step 4 — Link the new shop's products to existing ones (`ProductShop`)**

Steps 1–3 (adapter, registry, DB row) are implemented and are enough for the new shop to start being polled by `fetch_all()`. To show its prices next to existing products, `ProductShop` links are needed.

> **Direction of growth (not implemented, not required by the assignment):** a separate task `seed_new_shop_task(shop_id)` that, for production, matches the new shop's products to existing ones (fuzzy-matching by title, see 5.7) and creates `ProductShop`. Within the assignment, the initial mapping is done by the shared `seed_products()` by index on first run. The business logic, endpoints, and PriceService do not change when a shop is added.

### 5.7 Mapping products between shops

**The strategy for this assignment — mapping by index at initialization.**

On first run `seed_products()` runs, loading products from all shops and combining them by position in the list. This matches the assignment condition: *"you may combine ids from different APIs arbitrarily"*.

```python
# app/tasks/seed.py
async def seed_products(db: AsyncSession) -> None:
    dummy_products     = await DummyJsonAdapter().fetch_products()   # ~194 products (paginated)
    fakestore_products = await FakeStoreAdapter().fetch_products()   # 20 products

    for i, dummy in enumerate(dummy_products):
        # Create a single logical product entity.
        # Take the description from DummyJSON and fix the source (see section 3.3)
        product = Product(
            title=dummy.title,
            description=dummy.description,
            category=dummy.category,
            description_source_shop_id=DUMMYJSON_SHOP_ID,
        )
        db.add(product)

        # Link to DummyJSON — always present
        db.add(ProductShop(
            product=product,
            shop_id=DUMMYJSON_SHOP_ID,
            external_id=dummy.external_id,
        ))

        # Link to FakeStore — if there is a product with the same index
        if i < len(fakestore_products):
            db.add(ProductShop(
                product=product,
                shop_id=FAKESTORE_SHOP_ID,
                external_id=fakestore_products[i].external_id,
            ))

    await db.commit()
```

**Result:** the first 20 products (by index) get prices from two shops — DummyJSON and FakeStore, the other ~174 DummyJSON products — from one shop only. This is enough to demonstrate all features: the price range, per-shop history, and the chart.

**Idempotency:** before inserting, the existence of `ProductShop` by `(shop_id, external_id)` is checked — re-running the seed does not create duplicates.

> **Evolution path in production:** as the number of shops grows, mapping by index is replaced by a `ProductMatcherService` with fuzzy-matching by title (`rapidfuzz`) and extra signals (category, price proximity). The DB structure does not change — only the logic that fills `ProductShop`.

### 5.8 Lifespan — automatic seed run

The seed runs automatically through the FastAPI `lifespan` when `api` starts. Each step is checked independently (shops/products exist → skip), rates are always synced (idempotent upsert for today). The orchestration itself is `run_seed_if_needed()` in `app/tasks/seed.py` (next to `seed_shops`/`seed_products`), and `main.py` stays thin — only app assembly.

```python
# app/main.py — thin assembly
@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.run_seed_on_startup:        # true only in the api container
        await run_seed_if_needed()          # from app/tasks/seed.py
    yield
    await db_service.dispose()              # close the pool on shutdown

def create_app() -> FastAPI:
    app = FastAPI(title="Price Tracker API", lifespan=lifespan)
    register_exception_handlers(app)        # domain exceptions → HTTP
    app.include_router(api_router)
    return app

app = create_app()
```

```python
# app/tasks/seed.py — orchestration (simplified)
async def run_seed_if_needed() -> None:
    async with db_service.session() as db:
        await seed_demo_user(db)
        shops = (await db.execute(select(Shop))).scalars().all()
        shop_ids = {s.adapter_key: s.id for s in shops} or await seed_shops(db)
        if not await db.scalar(select(func.count(Product.id))):
            await seed_products(db, shop_ids)               # network failures do not break startup
        await CurrencyService(ExchangeRateRepo(db), redis_client).sync_today_rates()
        await db.commit()
```

> **Why we check for the presence of shops/products:** if they exist — the seed has already run. A simple and reliable flag without an extra table. Failures of external APIs during seed (shops/NBU) are logged but do not crash the app (graceful degradation).

> **`run_seed_on_startup` from `.env`:** the seed should run only in the `api` container, not in `worker` and `beat` — they also use the FastAPI context indirectly. The flag is controlled via an environment variable (see docker-compose below).



---

## 6. Background tasks (Celery)

### 6.1 List of tasks

| Task | Schedule | Purpose |
|---|---|---|
| `fetch_prices_task` | Every N hours (from `.env`) | Poll all active shops, write `PriceHistory` |
| `sync_exchange_rates_task` | Daily at 08:00 UTC | Load today's NBU rates |
| `check_price_alerts_task` | Every N minutes (from `.env`) | Check active alerts, send emails |
| `create_monthly_partition_task` | On the 1st of each month | Create a new partition of the `PriceHistory` table |

> **The shop polling interval (4 hours)** — a balance between data freshness and load on the external APIs. Configurable via `FETCH_PRICES_INTERVAL_HOURS` in `.env`.

### 6.2 app/tasks/celery_app.py

All task schedules are registered in one place — `beat_schedule`. The intervals are pulled from `settings`, nothing is hardcoded.

```python
from celery import Celery
from celery.schedules import crontab
from app.core.config import settings

app = Celery("price_tracker")

app.conf.update(
    broker_url=str(settings.celery_broker_url),
    result_backend=str(settings.celery_result_backend),
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

app.conf.beat_schedule = {
    # Price collection from shops — every N hours (from .env)
    "fetch-prices": {
        "task": "tasks.fetch_prices",
        "schedule": settings.fetch_prices_interval_hours * 3600,
    },

    # NBU rate sync — every day at SYNC_RATES_CRON_HOUR:00 UTC
    "sync-exchange-rates": {
        "task": "tasks.sync_exchange_rates",
        "schedule": crontab(hour=settings.sync_rates_cron_hour, minute=0),
    },

    # Alert check — every N minutes (from .env)
    "check-price-alerts": {
        "task": "tasks.check_price_alerts",
        "schedule": settings.check_alerts_interval_minutes * 60,
    },

    # Create a new PriceHistory partition — on the 1st of each month
    "create-price-history-partition-monthly": {
        "task": "tasks.create_price_history_partition",
        "schedule": crontab(day_of_month=1, hour=0, minute=5),
    },
}
```

### 6.3 Task files

Each task lives in a separate file and only calls the needed service. The business logic is in the services, the task is a thin wrapper.

```python
# app/tasks/prices.py
@app.task(name="tasks.fetch_prices")
def fetch_prices_task():
    asyncio.run(_fetch_prices_async())          # builds PriceFetcherService on a session

@app.task(name="tasks.create_price_history_partition")
def create_price_history_partition_task():
    asyncio.run(_create_partition_async())      # next month's partition

# app/tasks/rates.py
@app.task(name="tasks.sync_exchange_rates")
def sync_exchange_rates_task():
    asyncio.run(_sync_today_async())            # CurrencyService.sync_today_rates()

# app/tasks/alerts.py
@app.task(name="tasks.check_price_alerts")
def check_price_alerts_task():
    asyncio.run(_check_alerts_async())          # AlertService.check_alerts()
```

> The internal `_*_async()` wrappers open a session through `db_service`, assemble the service with the needed repositories (the same DI style as in the API), and commit.

---

## 7. Scaling

### 7.1 Partitioning PriceHistory

With millions of products and years of storage, `PriceHistory` will become the largest table. The solution is monthly partitioning:

```sql
CREATE TABLE price_history (
    id              BIGSERIAL,
    product_shop_id INT NOT NULL,
    price_usd       NUMERIC(12,4) NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL
) PARTITION BY RANGE (recorded_at);

-- Partitions are created automatically by a Celery task at the start of each month
CREATE TABLE price_history_2025_06
    PARTITION OF price_history
    FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
```

- **Advantages:** date-range queries touch only the needed partitions, old data can be archived (`DETACH PARTITION`).
- **Index on a partition:** the index is defined on the parent and inherited by every partition — `(product_shop_id, recorded_at DESC) INCLUDE (price_usd)` (see 7.5).
- **Partition pruning:** queries filtered by `recorded_at` (history for a period, "prices for today") are limited by the planner to only the needed partitions — this is the main mechanism for scaling over time.

### 7.2 Caching in Redis

| Key | Description |
|---|---|
| `exchange_rate:{currency}:{date}` | A currency rate. TTL: current day — 3600s, historical — indefinitely |

> **What is cached now:** currency rates — the "most expensive" data (an external call to the NBU). Reads go Redis → DB → NBU.
>
> **Direction of growth (not required by the assignment):** a cache of aggregated prices (`product_prices:{id}:{currency}`, TTL ~1h) and of the watchlist (`user_products:{user_id}`, TTL ~5min). At current volumes (a user's watchlist is small) these queries are cheap, so caching is deferred; TTLs for them are already reserved in the settings (`REDIS_TTL_PRODUCT_PRICES`, `REDIS_TTL_USER_PRODUCTS`).

### 7.3 Pagination

The product list is a user's watchlist (small), so offset pagination (`page` / `page_size`) is used — see 5.2. Cursor pagination (`cursor=<last_id>`) is a direction of growth for paging a global catalog with hundreds of thousands of records by an indexed field, where `OFFSET` becomes expensive.

### 7.4 Async I/O

FastAPI + async SQLAlchemy + httpx provide non-blocking processing. When polling several shops at once, `asyncio.gather()` is used for parallel requests.

### 7.5 Indexes and query optimization

Per the assignment: products — up to millions, price history — over years. The main and most write-hot table is `price_history`. Indexes are chosen **for the specific queries from the repositories**, not "just in case", and with the write cost in mind.

#### Principles

1. **We index hot paths measured from the code.** Each index has a specific justifying query (section 3.9). We do not add extra indexes — they slow down `INSERT`/`UPDATE`.
2. **FKs in Postgres are not indexed automatically.** Foreign-key columns we actually filter on (`product_shops.shop_id`, `price_alerts.user_id`) are indexed explicitly — otherwise a seq scan.
3. **We protect the write-hot table.** On `price_history` we keep the number of indexes minimal: the covering index **replaces** the old one, it is not added.

#### Applied techniques

**Partitioning + pruning (scaling over time).** `price_history` is partitioned by month (`RANGE (recorded_at)`). Date-range queries (history, "prices for today") hit only the needed partitions; old data is easy to archive (`DETACH PARTITION`). This is the primary mechanism for "years of history".

**Covering index → index-only scan.**
`price_history(product_shop_id, recorded_at DESC) INCLUDE (price_usd)`:
- `recorded_at DESC` — exactly for "last price"
  (`row_number() OVER (PARTITION BY product_shop_id ORDER BY recorded_at DESC)`)
  and for `ORDER BY` in history;
- `INCLUDE (price_usd)` — the only needed value sits in the index, so the read is **index-only**, with no heap lookup.
- Verified with `EXPLAIN`: `Index Only Scan` over the partitions.

**Partial index for a skewed boolean.**
`price_alerts(product_id) WHERE is_active`: the trigger check (`check_alerts`) looks only at active alerts, and they are deactivated after the first firing — over time the table is mostly "dead". The partial index stores only live rows: smaller and faster than a full one.

**A "filter + sort" composite.**
`price_alerts(user_id, created_at DESC)` covers the user's alert list query `WHERE user_id … ORDER BY created_at DESC` fully — without a separate sort step.

#### Query shape (not just indexes)

For lists and aggregates the prices are taken with **batch queries** (one selection of averages for today and for 30 days over the whole list, not a query per product) — eliminating N+1.

A known growth point: `latest_price_subq()` computes a window function over all `product_shop`, then filters by product. For reading a **single** product (`get_current_prices`) with millions of rows it is more efficient to push the `product_id` filter into the subquery, so the window is computed over 1–2 rows. Marked as a query-shape optimization (the schema/indexes do not change).

#### Operations

On large tables, indexes are created with `CREATE INDEX CONCURRENTLY` (no write lock). A nuance: on the partitioned `price_history` you cannot use `CONCURRENTLY` on the parent directly — the index is created on each partition, then `ATTACH`ed to the parent. The indexes themselves are defined in the models (so `create_all` and new partitions get them) and duplicated in an Alembic migration for existing DBs.

---

## 8. Currency module — NBU API

The official API of the National Bank of Ukraine is used. Free, no key required.

```
# Current rate (all currencies for today)
GET https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json

# A single currency's rate on a specific date
GET https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange
    ?valcode=USD&date=20240115&json

# Response:
[{
  "r030": 840,
  "txt": "US Dollar",
  "rate": 41.4,             // how many hryvnias per 1 unit of currency
  "cc": "USD",
  "exchangedate": "15.01.2024"
}]
```

**Important about the rate direction:** the NBU returns `rate` as "how many hryvnias per 1 unit of foreign currency". For USD this is ≈41.4 UAH per 1 USD. That is, the rate is always expressed relative to the hryvnia, not the dollar. This must be accounted for during conversion (see section 8.1).

### 8.1 Price conversion

Prices in the DB are stored in USD. To show a price in hryvnias, the UAH-to-USD rate is needed. To show it in euros — the EUR-to-USD rate, which is computed through the hryvnia as the intermediate currency.

```python
# Direct case: USD → UAH
# the NBU gives rate_usd = "hryvnias per 1 USD" (≈41.4)
price_uah = price_usd * rate_usd

# USD → EUR case (both currencies through UAH)
# rate_usd = hryvnias per 1 USD, rate_eur = hryvnias per 1 EUR
price_eur = price_usd * rate_usd / rate_eur
```

> **Storage decision:** in the `ExchangeRate` table the field stores exactly what the NBU returns — "how many hryvnias per 1 unit of currency" (the field is renamed to `rate_uah_per_unit`, see section 3.6). This removes ambiguity: USD and EUR are stored uniformly, and conversion between any two currencies goes through the hryvnia.

**Loading strategy:**

- On `api` startup today's rates are synced (idempotently).
- Daily at `SYNC_RATES_CRON_HOUR`:00 UTC a Celery task loads the rates for the current day.
- When a rate for any date is requested: Redis → PostgreSQL → if missing, a request to the NBU for that date (`?valcode=&date=`) + save to the DB → fallback to the nearest earlier rate. That is, **historical rates are pulled on-demand** as they are accessed (for example, when building price history).
- A one-off bulk backfill of history over a period — by the script `scripts/sync_historical_rates.py [DAYS]` (`sync_historical_rates()`).

> **Why not a bulk load of 5 years at startup:** it would slow down startup and would mostly load data that may never be needed. On-demand + the manual script cover the assignment requirement "fetch historical rates" without this cost. If needed, the preload is easy to move into a background task on first run.

---

## 9. Project structure

```
price_tracker/
├── app/
│   ├── api/
│   │   ├── __init__.py            # assembles api_router from the v1 routers
│   │   ├── deps.py                # DI: DB session, service providers, auth
│   │   ├── errors.py              # register_exception_handlers (domain → HTTP)
│   │   └── v1/
│   │       ├── products.py        # /products, /{id}, /{id}/prices, /{id}/price-history
│   │       ├── user_products.py   # GET/POST/DELETE /me/products (watchlist)
│   │       ├── alerts.py          # CRUD /me/alerts
│   │       ├── currencies.py      # GET /currencies
│   │       └── health.py          # GET /health
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── security.py            # JWT verify → TokenPayload
│   │   ├── exceptions.py          # domain exceptions (AppError/NotFound/Conflict)
│   │   ├── http_retry.py          # get_with_retry: retries to external APIs
│   │   ├── email.py               # send_email (SMTP / console mode)
│   │   ├── redis.py               # Redis client + factory for tasks
│   │   ├── logger.py              # logging setup
│   │   └── wait_for_db.py         # wait for the DB to be ready before start
│   ├── db/
│   │   ├── models/                # SQLAlchemy ORM — one entity per file
│   │   │   ├── base.py            # DeclarativeBase
│   │   │   ├── user.py  shop.py  product.py  product_shop.py
│   │   │   ├── price_history.py   # partitioned (RANGE recorded_at)
│   │   │   ├── exchange_rate.py  user_product.py  price_alert.py
│   │   └── repositories/          # Repository pattern (per entity)
│   │       ├── base.py            # BaseRepository (flush/refresh)
│   │       ├── product_repo.py  price_repo.py  alert_repo.py
│   │       ├── shop_repo.py  exchange_rate_repo.py  user_product_repo.py
│   │   └── __init__.py
│   ├── schemas/                   # Pydantic request/response + enums
│   │   ├── product.py  price.py  alert.py  currency.py
│   │   ├── enums.py               # Currency/TrendDirection/SortOption (StrEnum)
│   │   └── auth.py                # TokenPayload
│   ├── services/
│   │   ├── price_service.py       # price aggregation, trend, history
│   │   ├── currency_service.py    # conversion + NBU + cache
│   │   ├── alert_service.py       # alerts
│   │   ├── user_product_service.py# watchlist
│   │   ├── price_fetcher.py       # price collection from shops
│   │   ├── db_service.py          # engine/session (+ begin_task_session)
│   │   └── shop_adapters/
│   │       ├── base.py            # BaseShopAdapter + ShopProduct
│   │       ├── dummyjson.py  fakestore.py  registry.py
│   ├── tasks/
│   │   ├── celery_app.py          # Celery instance + beat_schedule
│   │   ├── prices.py              # fetch_prices_task + create_..._partition_task
│   │   ├── rates.py               # sync_exchange_rates_task
│   │   ├── alerts.py              # check_price_alerts_task
│   │   └── seed.py                # seed_*(), run_seed_if_needed()
│   └── main.py                    # create_app() factory + lifespan
├── alembic/versions/             # migrations (initial + scaling indexes)
├── scripts/
│   ├── generate_token.py          # static JWT for API testing
│   ├── run_check_alerts.py        # manual run of the alert check
│   └── sync_historical_rates.py   # one-off backfill of rate history
├── tests/                        # conftest.py + run.py + test_*.py (api/unit)
├── docker-compose.yml  Dockerfile  .dockerignore
├── .env.example               # config template (committed); .env — in .gitignore
├── pyproject.toml             # dependencies + ruff/mypy/pytest/coverage
└── uv.lock                    # lock file, committed to the repo
```

---

## 10. "To be clarified" decisions

| Question | Current decision / status |
|---|---|
| Alert deduplication | An alert is deactivated after the first firing. To clarify: re-activate automatically or only manually? |
| Mapping products between shops | Mapping by index at initialization (`seed_products`). The first 20 products get prices from two shops, the rest — only from DummyJSON. Replaced by fuzzy-matching in production. |
| Shop polling frequency | Current choice — every 4 hours. Should it be configurable per-shop? |
| Rate limiting of external APIs | DummyJSON and FakeStore may throttle requests. A retry strategy with exponential backoff is needed. |
| Email provider | SMTP for dev, SendGrid / AWS SES for production — the final choice depends on the infrastructure. |
| Authorization | A static JWT with no expiry. The token is generated once via `scripts/generate_token.py` and checked on every request via `verify_token` in `deps.py`. In production it is replaced with a JWT with `exp` + refresh. |

---

## 11. Sequence: price collection

A simplified diagram of how the background task works:

```
Celery Beat
   │
   └─► fetch_prices_task()
         │
         └─► PriceFetcherService.fetch_all()
               │
               └─► [for each Shop in the DB, in parallel via asyncio.gather()]
                     │
                     ├─► get_adapter(shop.adapter_key)
                     ├─► adapter.fetch_products()  ──► HTTP GET /products
                     │                                  (DummyJSON / FakeStore)
                     └─► save_price(product_shop_id, price_usd)
                           │
                           ├─► INSERT INTO price_history ...
                           └─► invalidate Redis cache (product_prices:{id}:*)
```

---

---

## 12. App configuration

All settings are stored in the `.env` file and read through `pydantic-settings`. Validation happens at startup — if a required variable is not set, the app fails immediately with a clear error, not at runtime.

### 12.1 app/core/config.py

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn

class Settings(BaseSettings):
    # ── Application ─────────────────────────────────────────
    app_env: str = "dev"                  # dev | prod
    app_secret_key: str                   # for signing the JWT
    debug: bool = False
    run_seed_on_startup: bool = False     # true only for the api container

    # ── Database ────────────────────────────────────────────
    database_url: PostgresDsn             # postgresql+asyncpg://...
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ── Redis ───────────────────────────────────────────────
    redis_url: RedisDsn                   # redis://redis:6379/0
    redis_ttl_exchange_rate: int = 3600   # seconds — current rate
    redis_ttl_product_prices: int = 3600  # seconds — aggregated prices
    redis_ttl_user_products: int = 300    # seconds — product list

    # ── Celery ──────────────────────────────────────────────
    celery_broker_url: RedisDsn           # redis://redis:6379/1
    celery_result_backend: RedisDsn       # redis://redis:6379/2
    fetch_prices_interval_hours: int = 4
    check_alerts_interval_minutes: int = 60
    sync_rates_cron_hour: int = 8         # UTC time for the rate sync

    # ── Email ───────────────────────────────────────────────
    # email_enabled=false → console mode (emails are logged). So SMTP_*
    # have defaults and are optional — the project runs without real SMTP.
    email_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@pricetracker.com"
    smtp_use_tls: bool = True

    # ── NBU API ─────────────────────────────────────────────
    nbu_api_url: str = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
    nbu_historical_years: int = 5         # how many years of history to load at init

    # ── External shop APIs ──────────────────────────────────
    dummyjson_url: str = "https://dummyjson.com"
    fakestore_url: str = "https://fakestoreapi.com"
    shop_api_timeout: int = 10            # seconds — shop request timeout
    shop_api_retry_attempts: int = 3      # attempts on error

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

settings = Settings()
```

### 12.2 .env.example

The `.env.example` file is committed to the repository as a template. The real `.env` is added to `.gitignore`.

```dotenv
# ── Application ─────────────────────────────────────────────
APP_ENV=dev
APP_SECRET_KEY=change-me-in-production
DEBUG=true
RUN_SEED_ON_STARTUP=false   # overridden in docker-compose for api

# ── Database ────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/price_tracker
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# ── Redis ───────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0
REDIS_TTL_EXCHANGE_RATE=3600
REDIS_TTL_PRODUCT_PRICES=3600
REDIS_TTL_USER_PRODUCTS=300

# ── Celery ──────────────────────────────────────────────────
CELERY_BROKER_URL=redis://redis:6379/1
CELERY_RESULT_BACKEND=redis://redis:6379/2
FETCH_PRICES_INTERVAL_HOURS=4
CHECK_ALERTS_INTERVAL_MINUTES=60
SYNC_RATES_CRON_HOUR=8

# ── Email (SMTP) ─────────────────────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@pricetracker.com
SMTP_USE_TLS=true

# ── NBU API ─────────────────────────────────────────────────
NBU_HISTORICAL_YEARS=5

# ── Shops ───────────────────────────────────────────────────
DUMMYJSON_URL=https://dummyjson.com
FAKESTORE_URL=https://fakestoreapi.com
SHOP_API_TIMEOUT=10
SHOP_API_RETRY_ATTEMPTS=3
```

### 12.3 Different environments

| File | Environment | Used |
|---|---|---|
| `.env` | local development | by default |
| `.env.prod` | production | `env_file=".env.prod"` or host environment variables |

In production, environment variables are passed directly through the host environment or secrets (Docker Secrets, Vault) — a `.env` file is not stored on the server.

### 12.4 Authorization — a JWT without expiry

Authorization is implemented minimally: a single static JWT token that is checked on every request. No registration, no login, no refresh tokens.

The Bearer token is extracted via `HTTPBearer`, the signature is verified (`python-jose`, HS256), and the payload is validated into a **typed** `TokenPayload` (see 5.x and `app/schemas/auth.py`) — `user_id` is required.

**app/core/security.py**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.auth import TokenPayload

_http_bearer = HTTPBearer()

def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_http_bearer),
) -> TokenPayload:
    try:
        raw = jwt.decode(credentials.credentials, settings.app_secret_key,
                         algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing token",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        return TokenPayload.model_validate(raw)   # user_id is required
    except ValidationError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token payload is invalid",
                            headers={"WWW-Authenticate": "Bearer"})
```

**Token generation — once, during project setup:**

```python
# scripts/generate_token.py
from jose import jwt
from app.core.config import settings

DEMO_USER_ID = "10000000-0000-0000-0000-000000000001"  # matches the seed
token = jwt.encode(
    {"sub": "admin", "role": "admin", "user_id": DEMO_USER_ID},
    settings.app_secret_key, algorithm="HS256",
)
print(f"Bearer {token}")
```

```bash
uv run python scripts/generate_token.py
# Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

The token is pasted into the Swagger UI ("Authorize" button) or into the `Authorization: Bearer <token>` header.

**Usage in endpoints via `deps.py`:**

```python
# app/api/deps.py
CurrentUser   = Annotated[TokenPayload, Depends(verify_token)]
CurrentUserId = Annotated[uuid.UUID, Depends(get_current_user_id)]  # → user.user_id
```

```python
# app/api/v1/products.py
@router.get("", response_model=ProductListResponse)
async def get_products(
    user_id: CurrentUserId,                 # checks the token + gives user_id
    service: PriceServiceDep,
    currency: Currency = Query(Currency.USD),
    sort: SortOption = Query(SortOption.PRICE_ASC),
) -> ProductListResponse:
    return await service.get_products_list(user_id, currency, page, page_size, sort)
```

> **Why no `exp`:** for the assignment a token expiry is not needed — the token is generated once and used for API testing. In production an `exp` and a refresh mechanism are added.

---

## 13. Running with Docker Compose

### 13.1 pyproject.toml

A single file for dependencies, dev dependencies, and tool settings. Committed together with `uv.lock`.

```toml
[project]
name = "price-tracker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pydantic-settings>=2.0",
    "pydantic[email]>=2.0",
    "celery[redis]>=5.3",
    "redis>=5.0",
    "httpx>=0.27",
    "bcrypt>=4.0",
    "python-jose[cryptography]>=3.3",
    "aiosmtplib>=5.1",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "httpx>=0.27",
    "ruff>=0.4",
    "mypy>=1.10",
]

[tool.ruff]
line-length = 88
target-version = "py312"

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### 13.2 Dockerfile

```dockerfile
FROM python:3.12-slim

# Copy UV from the official image — no need to install via pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only the dependency files — this layer is cached
# and is not rebuilt when the app code changes
COPY pyproject.toml uv.lock ./

# --frozen     — strictly from the lock file, no updates
# --no-dev     — prod dependencies only
# --no-cache   — do not keep a cache in the image
RUN uv sync --frozen --no-dev --no-cache

COPY . .

# Used as the base image for api, worker, beat, and migrate
```

### 13.3 app/core/wait_for_db.py

The `healthcheck` guarantees that postgres accepts connections, but in the first seconds the database may still not be fully ready. This script explicitly checks availability via a real SQL query before the app starts — with no extra dependencies, in pure Python.

```python
import asyncio
import sys
import logging
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings

logger = logging.getLogger(__name__)

async def wait_for_db(retries: int = 10, delay: int = 3) -> None:
    engine = create_async_engine(str(settings.database_url))
    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database is ready.")
            await engine.dispose()
            return
        except Exception as e:
            logger.warning(f"Attempt {attempt}/{retries} — DB not ready: {e}")
            if attempt == retries:
                logger.error("Database unavailable after all retries. Exiting.")
                sys.exit(1)
            await asyncio.sleep(delay)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(wait_for_db())
```

> `beat` does not use the script — it does not access the DB directly and depends only on `worker`.

### 13.4 docker-compose.yml

```yaml
services:

  # ── PostgreSQL ───────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: price_tracker
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5

  # ── Redis ────────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    restart: unless-stopped
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ── FastAPI application ──────────────────────────────────
  api:
    build: .
    command: >
      sh -c "python -m app.core.wait_for_db &&
             uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      RUN_SEED_ON_STARTUP: "true"   # the seed runs only here
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  # ── Celery Worker ────────────────────────────────────────
  worker:
    build: .
    command: >
      sh -c "python -m app.core.wait_for_db &&
             celery -A app.tasks.celery_app worker --loglevel=info --concurrency=4"
    restart: unless-stopped
    env_file: .env
    environment:
      RUN_SEED_ON_STARTUP: "false"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  # ── Celery Beat (scheduler) ──────────────────────────────
  beat:
    build: .
    command: celery -A app.tasks.celery_app beat --loglevel=info --scheduler celery.beat.PersistentScheduler
    restart: unless-stopped
    env_file: .env
    environment:
      RUN_SEED_ON_STARTUP: "false"
    depends_on:
      - worker

  # ── Migrations (runs once and exits) ─────────────────────
  migrate:
    build: .
    command: >
      sh -c "python -m app.core.wait_for_db &&
             alembic upgrade head"
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"

volumes:
  postgres_data:
  redis_data:
```

### 13.5 First-run order

```bash
# 1. Copy the config
cp .env.example .env
# edit .env — at minimum set SMTP_* and APP_SECRET_KEY

# 2. Build the images and start the infrastructure
docker compose up -d postgres redis

# 3. Apply the migrations
docker compose run --rm migrate

# 4. Start everything — the seed runs automatically inside api (lifespan)
docker compose up -d

# Check that the seed ran
docker compose logs api | grep -i seed
# Expected output:
# INFO: First run detected, seeding database...
# INFO: Seed completed successfully.

# Check the status of all containers
docker compose ps
```

> **The seed runs automatically** through the FastAPI `lifespan` when the `api` container starts. On later restarts it checks that the DB is already filled and skips (see section 5.8).

### 13.6 Useful commands

```bash
# ── UV (local development) ───────────────────────────────────
# Install all dependencies including dev
uv sync

# Add a new dependency
uv add httpx

# Add a dev dependency
uv add --dev pytest-asyncio

# Update the lock file
uv lock --upgrade

# Run a command in the project environment
uv run pytest
uv run alembic upgrade head

# ── Docker ───────────────────────────────────────────────────
# Restart only the API without a rebuild
docker compose restart api

# View the Celery queue
docker compose exec worker celery -A app.tasks.celery_app inspect active

# Connect to PostgreSQL
docker compose exec postgres psql -U postgres price_tracker

# Apply a new migration
docker compose run --rm migrate

# Stop everything and remove volumes (full reset)
docker compose down -v
```


---

*Price Tracker Service — Architecture document v1.0*
