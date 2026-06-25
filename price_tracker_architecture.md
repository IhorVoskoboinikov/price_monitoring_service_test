# Архитектурный документ
## Сервис отслеживания динамики цен на товары
**Price Tracker Service — v1.0**
*Тестовое задание: Middle+ / Senior Python Developer*

---

## Содержание

1. [Обзор системы](#1-обзор-системы)
2. [Технологический стек и обоснование](#2-технологический-стек-и-обоснование)
3. [Модели базы данных](#3-модели-базы-данных)
4. [API Эндпоинты](#4-api-эндпоинты)
5. [Архитектура сервисов и классов](#5-архитектура-сервисов-и-классов)
6. [Фоновые задачи (Celery)](#6-фоновые-задачи-celery)
7. [Масштабирование](#7-масштабирование)
8. [Валютный модуль — НБУ API](#8-валютный-модуль--нбу-api)
9. [Структура проекта](#9-структура-проекта)
10. [Решения «до уточнения»](#10-решения-до-уточнения)
11. [Последовательность: сбор цен](#11-последовательность-сбор-цен)
12. [Конфигурация и авторизация](#12-конфигурация-приложения)
13. [Запуск через Docker Compose](#13-запуск-через-docker-compose)

---

## 1. Обзор системы

Price Tracker — backend-сервис на Python, который собирает цены на товары из внешних API магазинов, хранит историю, конвертирует цены в нужную валюту и уведомляет пользователей об изменении цены.

### 1.1 Ключевые требования

- Пользователь регистрируется по email + пароль (auth выходит за рамки ТЗ).
- Пользователь формирует список товаров для отслеживания.
- Сервис периодически опрашивает API: `dummyjson.com/products` и `fakestoreapi.com/products`.
- Цены хранятся с историей (неограниченной по времени).
- Поддерживаются текущие и исторические курсы валют НБУ (Украина).
- API предоставляет список товаров с трендом, страницу товара, историю цен.
- Алерт на email при падении цены ниже указанного порога.

### 1.2 Контекстная диаграмма (C4 Level 1)

| Актор / Система | Роль |
|---|---|
| Пользователь | Регистрируется, настраивает список, просматривает цены и тренды |
| Price Tracker API | Основная система: хранит данные, предоставляет REST API |
| DummyJSON API | Внешний источник товаров и цен (`dummyjson.com`) |
| FakeStore API | Внешний источник товаров и цен (`fakestoreapi.com`) |
| НБУ API | Курсы валют Украины — `bank.gov.ua/NBUStatService` |
| Email-провайдер | SMTP / SendGrid — доставка уведомлений об изменении цены |

---

## 2. Технологический стек и обоснование

| Технология | Обоснование выбора |
|---|---|
| Python 3.12 | Стабильный, хорошая поддержка async, богатая экосистема для веба |
| FastAPI | Нативный async, автогенерация OpenAPI, Pydantic v2 из коробки, высокая производительность vs Django REST |
| PostgreSQL 16 | ACID, поддержка партиционирования таблиц (`PARTITION BY RANGE` для истории цен), хорошие JSON-операторы |
| SQLAlchemy 2.x + Alembic | ORM с async-поддержкой (`AsyncSession`, `AsyncEngine`), Alembic для миграций — стандарт для Python |
| Redis 7 | Кеш курсов валют и агрегированных цен (TTL), брокер для Celery |
| Celery + Celery Beat | Периодические задачи (сбор цен, проверка алертов, обновление курсов). Beat = cron-заменитель без cronjob |
| Pydantic v2 | Схемы запросов/ответов, валидация, сериализация. v2 — в 5–20x быстрее v1 |
| httpx | Async HTTP-клиент для запросов к внешним API магазинов и НБУ |
| UV | Менеджер пакетов — заменяет pip + virtualenv + pip-tools. Lock-файл, разделение dev/prod зависимостей, установка в 10-100x быстрее pip в Docker |
| НБУ API | `bank.gov.ua/NBUStatService` — бесплатный, официальный, поддерживает историю |

> **Почему не Django:** FastAPI + SQLAlchemy дают более чистый async без overhead Django ORM. Для API-only сервиса без шаблонов Django избыточен.

> **Почему UV, а не requirements.txt:** `requirements.txt` не фиксирует транзитивные зависимости без `pip-compile`, не разделяет dev/prod, медленно устанавливается в Docker. UV решает все три проблемы: `uv.lock` — точный снимок всего дерева зависимостей, `uv sync --frozen --no-dev` в Docker устанавливает только prod-зависимости из lock-файла за секунды.

> **Почему НБУ API:** официальный источник, бесплатный, предоставляет исторические курсы по дате (`GET /NBUStatService/v1/statdirectory/exchange?valcode=USD&date=YYYYMMDD&json`). Альтернативы — `exchangerate.host` или `openexchangerates.org` — либо платные, либо менее надёжны для UAH.

---

## 3. Модели базы данных

### 3.1 User

Пользователь системы. Полноценный auth выходит за рамки ТЗ — используется статический JWT (см. раздел 12.4). Поле `password_hash` зарезервировано на будущее: в текущей версии регистрация/логин не реализованы, поэтому оно не заполняется.

| Поле | Тип / описание |
|---|---|
| `id` | UUID, PK, `default gen_random_uuid()` |
| `email` | VARCHAR(255), UNIQUE NOT NULL |
| `password_hash` | VARCHAR(255) NOT NULL — bcrypt hash (зарезервировано, см. выше) |
| `is_active` | BOOLEAN, default TRUE |
| `created_at` | TIMESTAMPTZ, default NOW() |

### 3.2 Shop

Магазин — источник цен. Паттерн адаптера привязан к полю `adapter_key`.

| Поле | Тип / описание |
|---|---|
| `id` | SERIAL, PK |
| `name` | VARCHAR(100) NOT NULL — `'DummyJSON'`, `'FakeStore'` |
| `base_url` | VARCHAR(255) — базовый URL API |
| `adapter_key` | VARCHAR(50) UNIQUE — ключ для фабрики адаптеров (`'dummyjson'`, `'fakestore'`) |
| `is_active` | BOOLEAN — включён ли магазин в опрос |

### 3.3 Product

Товар — логическая сущность, не привязанная к конкретному магазину.

| Поле | Тип / описание |
|---|---|
| `id` | UUID, PK |
| `title` | VARCHAR(500) NOT NULL |
| `description` | TEXT |
| `category` | VARCHAR(200) |
| `description_source_shop_id` | INT, FK → `Shop.id`, nullable — из какого магазина взято описание |
| `created_at` | TIMESTAMPTZ |

> **Выбор описания (требование ТЗ «описание можно выбирать из любого API»):** один товар может присутствовать в нескольких магазинах с разными описаниями. Правило для текущей версии — описание берётся из магазина с наименьшим приоритетом `shop_id` (фактически первый магазин, в котором товар появился при seed), и фиксируется в `description_source_shop_id`. Это делает выбор детерминированным и прозрачным. Если в production понадобится другой приоритет (например, самое длинное или самое свежее описание) — меняется только логика заполнения этого поля, схема не меняется.

### 3.4 ProductShop

Связь товара с магазином. Хранит `external_id` товара в конкретном магазине. Один товар может присутствовать в нескольких магазинах с разными ID.

| Поле | Тип / описание |
|---|---|
| `id` | SERIAL, PK |
| `product_id` | UUID, FK → `Product.id` |
| `shop_id` | INT, FK → `Shop.id` |
| `external_id` | VARCHAR(100) — ID товара в API магазина |
| UNIQUE | `(product_id, shop_id)` |

### 3.5 PriceHistory ⭐

Главная таблица. Хранит каждое зафиксированное значение цены от конкретного магазина. Партиционирована по дате для масштабирования до миллионов записей.

| Поле | Тип / описание |
|---|---|
| `id` | BIGSERIAL, PK (включён в ключ партиции) |
| `product_shop_id` | INT, FK → `ProductShop.id` |
| `price_usd` | NUMERIC(12, 4) NOT NULL — цена всегда в USD |
| `recorded_at` | TIMESTAMPTZ NOT NULL — время снятия цены |
| PARTITION BY | `RANGE (recorded_at)` — по месяцам |

> **Важно:** цены хранятся только в USD. Конвертация в UAH/EUR/другие — на лету через `ExchangeRate`. Это исключает дублирование данных и позволяет ретроспективно пересчитать по историческому курсу.

### 3.6 ExchangeRate

Курс валюты к гривне на конкретную дату. Заполняется Celery-задачей раз в сутки через НБУ API. НБУ отдаёт курс как «сколько гривен за 1 единицу валюты» — храним в том же виде для единообразия (см. раздел 8.1).

| Поле | Тип / описание |
|---|---|
| `id` | SERIAL, PK |
| `currency_code` | CHAR(3) NOT NULL — `'USD'`, `'EUR'`, `'GBP'` |
| `rate_uah_per_unit` | NUMERIC(16, 8) NOT NULL — сколько гривен за 1 единицу валюты (для USD ≈ 41.4) |
| `date` | DATE NOT NULL |
| `source` | VARCHAR(50) — `'NBU'` |
| UNIQUE | `(currency_code, date)` |

> **Гривна как опорная валюта:** UAH не хранится отдельной строкой (её курс к самой себе = 1). Конвертация USD → EUR идёт через гривну: `price_usd * rate_usd / rate_eur`.

### 3.7 UserProduct

Список товаров пользователя для отслеживания. Связь многие-ко-многим.

| Поле | Тип / описание |
|---|---|
| `user_id` | UUID, FK → `User.id` |
| `product_id` | UUID, FK → `Product.id` |
| `added_at` | TIMESTAMPTZ |
| PK | `(user_id, product_id)` |

### 3.8 PriceAlert

Алерт на email: если цена на товар опускается ниже `threshold_price` — отправить письмо.

| Поле | Тип / описание |
|---|---|
| `id` | UUID, PK |
| `user_id` | UUID, FK → `User.id` |
| `product_id` | UUID, FK → `Product.id` |
| `threshold_price_usd` | NUMERIC(12, 4) — пороговая цена в USD |
| `currency_code` | CHAR(3) — в какой валюте указан порог |
| `is_active` | BOOLEAN — деактивируется после срабатывания |
| `triggered_at` | TIMESTAMPTZ — когда сработал |
| `created_at` | TIMESTAMPTZ |

### 3.9 Индексы

Индексируются конкретные «горячие» пути запросов; подробное обоснование и
техники (covering / partial / partition pruning / write-amplification) — в
разделе 7.5.

**Явные индексы:**

| Индекс | Под какой запрос |
|---|---|
| `price_history(product_shop_id, recorded_at DESC) INCLUDE (price_usd)` | «Последняя цена магазина» и история цен. Покрывающий → index-only scan. Наследуется партициями (см. 7.1) |
| `product_shops(product_id)` | JOIN товар→магазины при агрегации цен |
| `product_shops(shop_id)` | Фетчер: связи по магазину (`list_product_shops(shop_id)`) |
| `price_alerts(user_id, created_at DESC)` | Список алертов пользователя (фильтр + сортировка) |
| `price_alerts(product_id) WHERE is_active` | Partial: проверка срабатывания смотрит только активные |
| `exchange_rates(currency_code, date)` | UNIQUE — lookup курса и `≤ date` (fallback) |

**Покрыто PK / UNIQUE (отдельный индекс не нужен):**

| Запрос | Чем покрыт |
|---|---|
| Watchlist пользователя (`WHERE user_id`) | PK `user_products(user_id, product_id)` — leading `user_id` |
| Курс по дате/валюте | UNIQUE `(currency_code, date)` |
| Пользователь по email | UNIQUE `users(email)` |
| Магазин по adapter_key | UNIQUE `shops(adapter_key)` |
| Точечные lookup'ы по id | первичные ключи |

> Сознательно **не** индексируем `products.description_source_shop_id` (нигде не
> фильтруется) — лишний индекс только удорожает запись.

---

## 4. API Эндпоинты

Все эндпоинты требуют авторизации (Bearer JWT). Параметр `currency` (по умолчанию `USD`) поддерживается везде, где возвращаются цены.

### 4.1 Товары — список

```
GET /api/v1/products
```

| Параметр | Описание |
|---|---|
| Query params | `currency=UAH\|USD\|EUR` (default: `USD`) |
| | `sort=price_asc\|price_desc\|trend_asc\|trend_desc` |
| | Пагинация: `page` / `page_size` (offset, см. 5.2) |
| Ответ 200 | `{ items: [ProductListItem], page, page_size, total }` |
| `ProductListItem` | `id, title, price_min, price_max, currency, trend: up\|down\|same` |
| Логика `trend` | Средняя цена сегодня vs средняя за 30 дней, порог ±1% (детали в разделе 5.2) |

### 4.2 Товар — детальная страница

```
GET /api/v1/products/{product_id}
```

| Параметр | Описание |
|---|---|
| Query params | `currency=USD` |
| Ответ 200 | `id, title, description, category, price_min, price_max, currency, shops_count` |
| `shops_count` | Количество магазинов, где товар сейчас в наличии (число строк `ProductShop` для товара). Используется для UI — показать «доступен в N магазинах» |

### 4.3 Все цены по магазинам

```
GET /api/v1/products/{product_id}/prices
```

| Параметр | Описание |
|---|---|
| Query params | `currency=USD` |
| Ответ 200 | `{ items: [{ shop_name, price, currency, last_updated }] }` |
| Описание | Последняя зафиксированная цена от каждого магазина, где есть товар |

### 4.4 История цен

```
GET /api/v1/products/{product_id}/price-history
```

| Параметр | Описание |
|---|---|
| Query params | `currency=USD`, `date_from=YYYY-MM-DD`, `date_to=YYYY-MM-DD` |
| Ответ 200 | `{ series: [{ shop_name, data: [{ date, price }] }], average: [{ date, price }] }` |
| Описание | Данные для графика: серия по каждому магазину + средняя цена по дням |

> **Средняя при разных периодах истории (требование ТЗ «история цен в разных магазинах может быть разной»):** у магазина A может быть цена за январь, у магазина B — только с марта. Средняя за каждый день считается **только по тем магазинам, у которых есть запись в этот день** — `average[date] = avg(цены всех магазинов, имевших запись в date)`. Дни без данных у магазина не считаются нулём (это исказило бы среднюю), а просто исключаются из расчёта для этого дня. На графике линия магазина начинается с его первой записи и обрывается на последней — фронтенд не соединяет разрывы. Каждая точка конвертируется в выбранную валюту по курсу своей даты (см. раздел 5.3).

### 4.5 Список товаров пользователя

| Метод + URL | Описание |
|---|---|
| `GET /api/v1/me/products` | Список отслеживаемых товаров текущего пользователя |
| `POST /api/v1/me/products` | Body: `{ product_id }`. Добавить товар в список |
| `DELETE /api/v1/me/products/{product_id}` | Убрать товар из отслеживания |

### 4.6 Алерты

| Метод + URL | Описание |
|---|---|
| `GET /api/v1/me/alerts` | Список алертов пользователя |
| `POST /api/v1/me/alerts` | Body: `{ product_id, threshold_price, currency }`. Создать алерт |
| `DELETE /api/v1/me/alerts/{alert_id}` | Удалить алерт |

### 4.7 Служебные эндпоинты

| Метод + URL | Описание |
|---|---|
| `GET /api/v1/currencies` | Список доступных валют с текущим курсом |
| `GET /api/v1/health` | Liveness-проба приложения (`{"status": "ok"}`) |

> **Health-check:** в текущей версии — простая liveness-проба, что процесс
> поднят и отвечает (этого достаточно для healthcheck в Docker Compose). Глубокая
> readiness-проверка (БД, Redis, доступность воркеров) — путь развития для
> production-мониторинга; в рамках ТЗ не требуется.

---

## 5. Архитектура сервисов и классов

### 5.0 Принцип асинхронности

Все сервисы, репозитории и адаптеры, которые выполняют I/O операции, реализуются как **async**. Это позволяет FastAPI обрабатывать множество запросов параллельно без блокировки event loop.

| Компонент | Async | Причина |
|---|---|---|
| FastAPI эндпоинты | ✅ `async def` | Нативная поддержка, точка входа |
| Сервисы (`PriceService`, `CurrencyService`, `AlertService`) | ✅ `async def` | Делают запросы к БД и Redis |
| Репозитории (`ProductRepo`, `PriceRepo`) | ✅ `async def` | Все запросы через async SQLAlchemy |
| Адаптеры магазинов (`DummyJsonAdapter`, `FakeStoreAdapter`) | ✅ `async def` | HTTP-запросы через `httpx.AsyncClient` |
| `CurrencyService.get_rate()` | ✅ `async def` | Запросы к Redis и БД, иногда к НБУ API |
| `wait_for_db.py` | ✅ `asyncio.run()` | Проверка соединения через async SQLAlchemy |
| Celery-задачи | ⚠️ sync обёртка | Celery не поддерживает async напрямую — задача синхронная, внутри вызывает `asyncio.run(service.method())` |
| `config.py` / `Settings` | ❌ sync | Просто чтение переменных, I/O нет |
| Pydantic-схемы | ❌ sync | Валидация данных, I/O нет |

> **Celery и async:** Celery worker работает в синхронном контексте. Поэтому каждая задача — это тонкая синхронная обёртка, которая запускает асинхронный сервис через `asyncio.run()`. Логика остаётся в async-сервисах, задача только инициирует запуск.

```python
# ✅ Правильно — сервис async, задача — sync обёртка
@app.task
def check_price_alerts_task():
    asyncio.run(AlertService().check_alerts())  # async внутри

# ✅ Правильно — репозиторий и сервис async
class PriceService:
    async def get_current_prices(self, product_id: UUID, currency: str) -> list[PriceItem]:
        rows = await self.price_repo.get_latest_prices(product_id)   # async запрос к БД
        # convert учитывает направление курса и дату (см. CurrencyService)
        return [
            PriceItem(price=await self.currency_service.convert(row.price_usd, currency))
            for row in rows
        ]

# ✅ Правильно — адаптер async
class DummyJsonAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        async with httpx.AsyncClient() as client:           # async HTTP
            resp = await client.get(f"{self.base_url}/products")
        return [ShopProduct(...) for p in resp.json()["products"]]
```



### 5.1 Паттерн адаптера магазинов

Для расширяемости список магазинов изолирован за единым интерфейсом `BaseShopAdapter`. Новый магазин — новый класс + регистрация в реестре. Бизнес-логика не меняется.

#### Проблема: разные структуры ответов

Оба магазина возвращают разную структуру — адаптер скрывает эту разницу от остальной системы.

**FakeStore** — возвращает чистый массив:
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

**DummyJSON** — оборачивает в объект с пагинацией, полей значительно больше:
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

#### Решение: единый внутренний формат

Оба адаптера преобразуют свой ответ в `ShopProduct`. Всё что выше — сервисы, БД, бизнес-логика — работает только с `ShopProduct` и не знает о деталях внешних API.

```python
@dataclass
class ShopProduct:
    external_id: str
    title: str
    description: str
    category: str
    price_usd: float
    # лишние поля (stock, brand, sku, discountPercentage) просто игнорируются
```

```python
class BaseShopAdapter(ABC):
    @abstractmethod
    async def fetch_products(self) -> list[ShopProduct]:
        """Вернуть список товаров с ценами."""

    @abstractmethod
    async def fetch_product(self, external_id: str) -> ShopProduct | None:
        """Вернуть один товар по ID."""


class FakeStoreAdapter(BaseShopAdapter):
    async def fetch_products(self) -> list[ShopProduct]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/products")
        # FakeStore отдаёт чистый массив [...]
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
        # DummyJSON отдаёт максимум часть товаров за раз (всего ~194),
        # поэтому листаем по skip/limit пока не выберем все
        products: list[ShopProduct] = []
        skip, limit = 0, 100
        async with httpx.AsyncClient() as client:
            while True:
                resp = await client.get(
                    f"{self.base_url}/products?limit={limit}&skip={skip}"
                )
                data = resp.json()
                # DummyJSON оборачивает в {"products": [...], "total": 194, ...}
                for p in data["products"]:
                    products.append(ShopProduct(
                        external_id=str(p["id"]),
                        title=p["title"],
                        description=p["description"],
                        category=p["category"],
                        price_usd=p["price"],
                        # остальные поля (stock, brand, sku...) игнорируем
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

> **Ключевой принцип:** адаптер знает всё о своём магазине и ничего лишнего не пропускает наружу. Добавление нового магазина с любой структурой ответа — это только новый класс адаптера, больше ничего в системе не меняется.

### 5.2 PriceService

Основная бизнес-логика: агрегация цен, вычисление тренда, конвертация.

| Метод | Описание |
|---|---|
| `get_products_list(user_id, currency, sort)` | Список товаров пользователя с диапазоном цен и трендом |
| `get_product_detail(product_id, currency)` | Детальная карточка товара |
| `get_current_prices(product_id, currency)` | Текущая цена от каждого магазина |
| `get_price_history(product_id, currency, date_from, date_to)` | История цен для графика по магазинам и средняя |
| `calculate_trend(product_id)` | Сравнивает avg сегодня vs avg за 30 дней → `up`/`down`/`same` |

#### Логика диапазона цен и тренда

У товара может быть несколько магазинов с разными ценами. Нужно чётко определить, что показываем:

- **`price_min` / `price_max` за сегодня** — минимальная и максимальная цена среди всех магазинов, где есть товар, по последним записям за текущий день.
- **Тренд** считается так: берётся средняя цена товара за сегодня (среднее по всем магазинам) и сравнивается со средней ценой за предыдущие 30 дней (среднее всех записей всех магазинов за период). Результат:
  - `up` — если `avg_today > avg_30d * 1.01`
  - `down` — если `avg_today < avg_30d * 0.99`
  - `same` — если разница в пределах ±1%

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

> Тренд считается в USD (на исходных ценах) — конвертация валюты не влияет на направление тренда, поэтому считать его до конвертации корректнее и дешевле.

#### Сортировка и пагинация

Список — это watchlist конкретного пользователя, он невелик (единицы–десятки
товаров), а тренд и диапазон цен — вычисляемые поля (агрегаты по нескольким
магазинам). Поэтому применяется обычная `OFFSET`-пагинация (`page` / `page_size`)
по уже агрегированному и отсортированному в памяти результату — для всех видов
сортировки одинаково. Это просто и достаточно для объёмов watchlist.

> **Путь развития (не требуется ТЗ):** если бы листался глобальный каталог
> (сотни тысяч–миллионы товаров) по индексируемому полю, для `sort=price_*`
> имело бы смысл перейти на курсорную пагинацию (`cursor=<last_id>`), чтобы
> избежать роста стоимости `OFFSET` на больших смещениях. Для пользовательского
> watchlist это избыточно.

### 5.3 CurrencyService

Управляет курсами валют. Кеширует в Redis (TTL для текущего курса из `.env`, исторические — бессрочно).

| Метод | Описание |
|---|---|
| `convert(amount_usd, currency, date=None)` | Конвертировать сумму из USD в указанную валюту на нужную дату. `date=None` → сегодняшний курс. Для исторических точек графика передаётся дата точки |
| `get_rate(currency, date)` | Вернуть курс «гривен за единицу валюты» из кеша или БД. Если нет — запрос к НБУ API |
| `sync_today_rates()` | Celery-задача: загрузить сегодняшние курсы всех валют с НБУ |
| `sync_historical_rates(date_from, date_to)` | Разовая загрузка исторических курсов при инициализации |

> **Исторические цены конвертируются по курсу своей даты.** В `get_price_history` для каждой точки графика берётся курс на дату этой точки, а не сегодняшний. Иначе график в гривне исказил бы реальную динамику. `convert()` принимает `date` именно для этого — каждая точка истории конвертируется по `get_rate(currency, point.date)`.

### 5.4 AlertService

Управляет алертами пользователей.

| Метод | Описание |
|---|---|
| `create_alert(user_id, product_id, threshold, currency)` | Создаёт `PriceAlert`. Порог конвертируется в USD по текущему курсу и хранится как `threshold_price_usd` |
| `check_alerts()` | Celery Beat, интервал из `.env`. Находит активные алерты, где минимальная цена товара (в USD) ≤ порога. Отправляет email и деактивирует |
| `send_alert_email(alert)` | Формирует письмо и отправляет через email-провайдер |

### 5.5 PriceFetcherService

Координирует сбор цен из магазинов.

| Метод | Описание |
|---|---|
| `fetch_all_shops()` | Celery Beat, интервал из `.env` (по умолчанию 4 часа). Запускает `fetch_shop()` для каждого активного магазина |
| `fetch_shop(shop_id)` | Через адаптер получает товары, записывает `PriceHistory` |
| `save_price(product_shop_id, price_usd)` | Сохраняет снимок цены. Избегает дублей за < 1 час |

### 5.6 Добавление нового магазина

Процесс полностью изолирован от бизнес-логики благодаря паттерну адаптера. Четыре шага:

**Шаг 1 — Реализовать адаптер**

```python
# app/shop_adapters/newshop.py
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

**Шаг 2 — Зарегистрировать в реестре**

```python
# app/shop_adapters/registry.py
ADAPTERS: dict[str, type[BaseShopAdapter]] = {
    'dummyjson': DummyJsonAdapter,
    'fakestore': FakeStoreAdapter,
    'newshop':   NewShopAdapter,   # <-- добавить строку
}
```

**Шаг 3 — Добавить запись в БД**

```sql
INSERT INTO shop (name, base_url, adapter_key, is_active)
VALUES ('NewShop', 'https://newshop.com/api', 'newshop', true);
```

Это делается через Alembic data-migration или seed-скрипт. Перезапуск приложения не требуется — `fetch_all_shops()` читает список магазинов из БД при каждом запуске задачи.

**Шаг 4 — Связать товары нового магазина с существующими (`ProductShop`)**

Шаги 1–3 (адаптер, реестр, запись в БД) реализованы и достаточны, чтобы новый
магазин начал опрашиваться `fetch_all()`. Для отображения его цен рядом с
существующими товарами нужны связи `ProductShop`.

> **Путь развития (не реализовано, не требуется ТЗ):** отдельная задача
> `seed_new_shop_task(shop_id)`, которая для production сопоставляет товары
> нового магазина с существующими (fuzzy-matching по названию, см. 5.7) и создаёт
> `ProductShop`. В рамках ТЗ начальный маппинг делается общим `seed_products()`
> по индексу при первом запуске. Бизнес-логика, эндпоинты и PriceService при
> добавлении магазина не меняются.

### 5.7 Маппинг товаров между магазинами

**Стратегия для данного ТЗ — маппинг по индексу при инициализации.**

При первом запуске выполняется `seed_products()`, который загружает товары из всех магазинов и совмещает их по позиции в списке. Это соответствует условию ТЗ: *"можно совмещать id из разных API произвольным образом"*.

```python
# app/tasks/seed.py
async def seed_products(db: AsyncSession) -> None:
    dummy_products     = await DummyJsonAdapter().fetch_products()   # ~194 товара (с пагинацией)
    fakestore_products = await FakeStoreAdapter().fetch_products()   # 20 товаров

    for i, dummy in enumerate(dummy_products):
        # Создаём единую логическую сущность товара.
        # Описание берём из DummyJSON и фиксируем источник (см. раздел 3.3)
        product = Product(
            title=dummy.title,
            description=dummy.description,
            category=dummy.category,
            description_source_shop_id=DUMMYJSON_SHOP_ID,
        )
        db.add(product)

        # Привязываем к DummyJSON — есть всегда
        db.add(ProductShop(
            product=product,
            shop_id=DUMMYJSON_SHOP_ID,
            external_id=dummy.external_id,
        ))

        # Привязываем к FakeStore — если есть товар с тем же индексом
        if i < len(fakestore_products):
            db.add(ProductShop(
                product=product,
                shop_id=FAKESTORE_SHOP_ID,
                external_id=fakestore_products[i].external_id,
            ))

    await db.commit()
```

**Результат:** первые 20 товаров (по индексу) получают цены из двух магазинов — DummyJSON и FakeStore, остальные ~174 товара DummyJSON — только из одного магазина. Этого достаточно для демонстрации всех фич: диапазона цен, истории по магазинам и графика.

**Идемпотентность:** перед вставкой проверяется существование `ProductShop` по `(shop_id, external_id)` — повторный запуск seed не создаёт дублей.

> **Путь эволюции в production:** при росте числа магазинов маппинг по индексу заменяется на `ProductMatcherService` с fuzzy-matching по title (`rapidfuzz`) и дополнительными сигналами (категория, ценовая близость). Структура БД при этом не меняется — только логика заполнения `ProductShop`.

### 5.8 Lifespan — автоматический запуск seed

Вместо ручного запуска seed-скрипта используется FastAPI `lifespan` — функция, которая выполняется автоматически при старте приложения. Seed запускается только если база пустая (первый запуск), при повторных стартах пропускается.

```python
# app/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import func, select
from app.db.models import Shop
from app.db.session import get_session
from app.tasks.seed import seed_shops, seed_products
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── STARTUP ──────────────────────────────────────────────
    if settings.run_seed_on_startup:
        await run_seed_if_needed()
    yield
    # ── SHUTDOWN ─────────────────────────────────────────────
    # закрытие пула соединений, если нужно

async def run_seed_if_needed() -> None:
    async with get_session() as db:
        result = await db.execute(select(func.count(Shop.id)))
        shops_count = result.scalar()

        if shops_count == 0:
            # База пустая — первый запуск
            logger.info("First run detected, seeding database...")
            await seed_shops(db)
            await seed_products(db)
            logger.info("Seed completed successfully.")
        else:
            logger.info("Database already seeded, skipping.")

        # Курсы синхронизируются всегда (идемпотентно), не только при первом запуске
        await sync_today_rates(db)

app = FastAPI(lifespan=lifespan)
```

> **Почему проверяем `Shop.count == 0`:** если магазины уже есть — значит seed уже запускался. Это простой и надёжный флаг без лишней таблицы.

> **`run_seed_on_startup` из `.env`:** seed должен запускаться только в контейнере `api`, не в `worker` и `beat` — они тоже используют FastAPI контекст косвенно. Флаг управляется через переменную окружения (см. docker-compose ниже).



---

## 6. Фоновые задачи (Celery)

### 6.1 Список задач

| Задача | Расписание | Назначение |
|---|---|---|
| `fetch_prices_task` | Каждые N часов (из `.env`) | Опрос всех активных магазинов, запись `PriceHistory` |
| `sync_exchange_rates_task` | Ежедневно в 08:00 UTC | Загрузка курсов НБУ на сегодня |
| `check_price_alerts_task` | Каждые N минут (из `.env`) | Проверка активных алертов, отправка email |
| `create_monthly_partition_task` | 1-го числа каждого месяца | Создание новой партиции таблицы `PriceHistory` |

> **Интервал опроса магазинов (4 часа)** — баланс между актуальностью данных и нагрузкой на внешние API. Настраивается через `FETCH_PRICES_INTERVAL_HOURS` в `.env`.

### 6.2 app/tasks/celery_app.py

Все расписания задач регистрируются в одном месте — `beat_schedule`. Интервалы тянутся из `settings`, ничего не захардкожено.

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
    # Сбор цен из магазинов — каждые N часов (из .env)
    "fetch-prices": {
        "task": "tasks.fetch_prices",
        "schedule": settings.fetch_prices_interval_hours * 3600,
    },

    # Синхронизация курсов НБУ — каждый день в SYNC_RATES_CRON_HOUR:00 UTC
    "sync-exchange-rates": {
        "task": "tasks.sync_exchange_rates",
        "schedule": crontab(hour=settings.sync_rates_cron_hour, minute=0),
    },

    # Проверка алертов — каждые N минут (из .env)
    "check-price-alerts": {
        "task": "tasks.check_price_alerts",
        "schedule": settings.check_alerts_interval_minutes * 60,
    },

    # Создание новой партиции PriceHistory — 1-го числа каждого месяца
    "create-price-history-partition-monthly": {
        "task": "tasks.create_price_history_partition",
        "schedule": crontab(day_of_month=1, hour=0, minute=5),
    },
}
```

### 6.3 Файлы задач

Каждая задача живёт в отдельном файле и только вызывает нужный сервис. Бизнес-логика — в сервисах, задача — тонкая обёртка.

```python
# app/tasks/prices.py
@app.task(name="tasks.fetch_prices")
def fetch_prices_task():
    asyncio.run(_fetch_prices_async())          # строит PriceFetcherService на сессии

@app.task(name="tasks.create_price_history_partition")
def create_price_history_partition_task():
    asyncio.run(_create_partition_async())      # партиция следующего месяца

# app/tasks/rates.py
@app.task(name="tasks.sync_exchange_rates")
def sync_exchange_rates_task():
    asyncio.run(_sync_today_async())            # CurrencyService.sync_today_rates()

# app/tasks/alerts.py
@app.task(name="tasks.check_price_alerts")
def check_price_alerts_task():
    asyncio.run(_check_alerts_async())          # AlertService.check_alerts()
```

> Внутренние `_*_async()`-обёртки открывают сессию через `db_service`, собирают
> сервис с нужными репозиториями (тот же DI-стиль, что в API) и коммитят.

---

## 7. Масштабирование

### 7.1 Партиционирование PriceHistory

При миллионах товаров и годах хранения `PriceHistory` станет самой большой таблицей. Решение — партиционирование по месяцам:

```sql
CREATE TABLE price_history (
    id              BIGSERIAL,
    product_shop_id INT NOT NULL,
    price_usd       NUMERIC(12,4) NOT NULL,
    recorded_at     TIMESTAMPTZ NOT NULL
) PARTITION BY RANGE (recorded_at);

-- Партиции создаются автоматически Celery-задачей в начале каждого месяца
CREATE TABLE price_history_2025_06
    PARTITION OF price_history
    FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
```

- **Преимущества:** запросы по диапазону дат затрагивают только нужные партиции, старые данные можно архивировать (`DETACH PARTITION`).
- **Индекс на партиции:** индекс задаётся на родителе и наследуется каждой
  партицией — `(product_shop_id, recorded_at DESC) INCLUDE (price_usd)` (см. 7.5).
- **Partition pruning:** запросы с фильтром по `recorded_at` (история за период,
  «цены на сегодня») планировщик ограничивает только нужными партициями — это
  основной механизм масштаба по времени.

### 7.2 Кеширование в Redis

| Ключ | Описание |
|---|---|
| `exchange_rate:{currency}:{date}` | Курс валюты. TTL: текущий день — 3600с, исторический — бессрочно |

> **Что кешируется сейчас:** курсы валют — самые «дорогие» данные (внешний
> вызов к НБУ). Чтение идёт Redis → БД → НБУ.
>
> **Путь развития (не требуется ТЗ):** кеш агрегированных цен
> (`product_prices:{id}:{currency}`, TTL ~1ч) и списка watchlist
> (`user_products:{user_id}`, TTL ~5мин). На текущих объёмах (watchlist
> пользователя невелик) эти запросы дёшевы, поэтому кеш отложен; TTL под них
> уже зарезервированы в настройках (`REDIS_TTL_PRODUCT_PRICES`,
> `REDIS_TTL_USER_PRODUCTS`).

### 7.3 Пагинация

Список товаров — это watchlist пользователя (небольшой), поэтому используется
offset-пагинация (`page` / `page_size`) — см. 5.2. Курсорная пагинация
(`cursor=<last_id>`) — путь развития на случай листания глобального каталога с
сотнями тысяч записей по индексируемому полю, где `OFFSET` становится дорогим.

### 7.4 Async I/O

FastAPI + async SQLAlchemy + httpx обеспечивают неблокирующую обработку. При опросе нескольких магазинов одновременно используется `asyncio.gather()` для параллельных запросов.

### 7.5 Индексы и оптимизация запросов

По ТЗ: товаров — до миллионов, история цен — за годы. Главная и самая
write-горячая таблица — `price_history`. Индексы подбираются **под конкретные
запросы из репозиториев**, а не «на всякий случай», и с учётом стоимости записи.

#### Принципы

1. **Индексируем горячие пути, измеренные по коду.** Для каждого индекса есть
   конкретный запрос-обоснование (раздел 3.9). Лишние индексы не заводим — они
   замедляют `INSERT`/`UPDATE`.
2. **FK в Postgres не индексируются автоматически.** Колонки внешних ключей,
   по которым реально фильтруем (`product_shops.shop_id`, `price_alerts.user_id`),
   индексируем явно — иначе seq scan.
3. **Бережём write-горячую таблицу.** На `price_history` число индексов держим
   минимальным: covering-индекс **заменяет** прежний, а не добавляется.

#### Применённые техники

**Партиционирование + pruning (масштаб по времени).** `price_history`
партиционирована по месяцам (`RANGE (recorded_at)`). Запросы по диапазону дат
(история, «цены на сегодня») бьют только нужные партиции; старые данные легко
архивировать (`DETACH PARTITION`). Это первичный механизм для «годов истории».

**Covering-индекс → index-only scan.**
`price_history(product_shop_id, recorded_at DESC) INCLUDE (price_usd)`:
- `recorded_at DESC` — точно под «последнюю цену»
  (`row_number() OVER (PARTITION BY product_shop_id ORDER BY recorded_at DESC)`)
  и под `ORDER BY` в истории;
- `INCLUDE (price_usd)` — единственное нужное значение лежит в индексе, поэтому
  чтение идёт **index-only**, без обращения к heap.
- Проверено `EXPLAIN`: `Index Only Scan` по партициям.

**Partial-индекс для перекошенного boolean.**
`price_alerts(product_id) WHERE is_active`: проверка срабатывания
(`check_alerts`) смотрит только активные алерты, а они деактивируются после
первого срабатывания — со временем таблица в основном «мёртвая». Частичный
индекс хранит только живые строки: меньше по размеру и быстрее полного.

**Композит «фильтр + сортировка».**
`price_alerts(user_id, created_at DESC)` закрывает запрос списка алертов
пользователя `WHERE user_id … ORDER BY created_at DESC` целиком — без отдельного
шага сортировки.

#### Форма запроса (не только индексы)

Для списков и агрегатов цены берутся **батч-запросами** (одна выборка средних за
сегодня и за 30 дней на весь список, а не запрос на товар) — устранение N+1.

Известная точка роста: `latest_price_subq()` считает оконную функцию по всем
`product_shop`, после чего фильтрует по товару. Для чтения **одного** товара
(`get_current_prices`) при миллионах строк эффективнее протолкнуть фильтр
`product_id` внутрь подзапроса, чтобы окно считалось по 1–2 строкам. Помечено
как оптимизация формы запроса (схема/индексы при этом не меняются).

#### Эксплуатация

На больших таблицах индексы создаются `CREATE INDEX CONCURRENTLY` (без блокировки
на запись). Нюанс: на партиционированной `price_history` `CONCURRENTLY` на
родителе напрямую нельзя — индекс создают на каждой партиции, затем `ATTACH` к
родителю. Сами индексы заданы в моделях (чтобы `create_all` и новые партиции их
получали) и продублированы Alembic-миграцией для существующих БД.

---

## 8. Валютный модуль — НБУ API

Используется официальный API Национального Банка Украины. Бесплатный, не требует ключа.

```
# Текущий курс (все валюты на сегодня)
GET https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?json

# Курс одной валюты на конкретную дату
GET https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange
    ?valcode=USD&date=20240115&json

# Ответ:
[{
  "r030": 840,
  "txt": "Долар США",
  "rate": 41.4,             // сколько гривен за 1 единицу валюты
  "cc": "USD",
  "exchangedate": "15.01.2024"
}]
```

**Важно про направление курса:** НБУ возвращает `rate` как «сколько гривен за 1 единицу иностранной валюты». Для USD это ≈41.4 UAH за 1 USD. То есть курс всегда выражен относительно гривны, а не доллара. Это нужно учитывать при конвертации (см. раздел 8.1).

### 8.1 Конвертация цен

Цены в БД хранятся в USD. Чтобы показать цену в гривне, нужен курс UAH к USD. Чтобы показать в евро — курс EUR к USD, который вычисляется через гривну как промежуточную валюту.

```python
# Прямой случай: USD → UAH
# НБУ даёт rate_usd = "гривен за 1 USD" (≈41.4)
price_uah = price_usd * rate_usd

# Случай USD → EUR (обе валюты через UAH)
# rate_usd = гривен за 1 USD, rate_eur = гривен за 1 EUR
price_eur = price_usd * rate_usd / rate_eur
```

> **Решение по хранению:** в таблице `ExchangeRate` поле хранит именно то, что отдаёт НБУ — «сколько гривен за 1 единицу валюты» (поле переименовано в `rate_uah_per_unit`, см. раздел 3.6). Это убирает двусмысленность: USD и EUR хранятся единообразно, конвертация между любыми двумя валютами идёт через гривну.

**Стратегия загрузки:**

- При старте `api` синхронизируются сегодняшние курсы (идемпотентно).
- Ежедневно в `SYNC_RATES_CRON_HOUR`:00 UTC Celery-задача загружает курсы на
  текущий день.
- При запросе курса на любую дату: Redis → PostgreSQL → если нет, запрос к НБУ
  по этой дате (`?valcode=&date=`) + сохранение в БД → fallback на ближайший
  предыдущий курс. То есть **исторические курсы подтягиваются on-demand** по мере
  обращения к ним (например, при построении истории цен).
- Разовая массовая догрузка истории за период — скриптом
  `scripts/sync_historical_rates.py [DAYS]` (`sync_historical_rates()`).

> **Почему не bulk-загрузка за 5 лет при старте:** она замедлила бы запуск и
> в основном грузила бы данные, которые могут не понадобиться. On-demand + ручной
> скрипт покрывают требование ТЗ «получать исторические курсы» без этой цены.
> При необходимости предзагрузку легко вынести в фоновую задачу первого запуска.

---

## 9. Структура проекта

```
price_tracker/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── products.py        # GET /products, /products/{id}
│   │   │   ├── prices.py          # GET /products/{id}/prices, /price-history
│   │   │   ├── user_products.py   # POST/DELETE /me/products
│   │   │   ├── alerts.py          # CRUD /me/alerts
│   │   │   └── currencies.py      # GET /currencies
│   │   └── deps.py                # DI: get_db, get_current_user
│   ├── core/
│   │   ├── config.py              # Settings (pydantic-settings)
│   │   ├── security.py            # JWT verify
│   │   └── wait_for_db.py         # ожидание готовности БД перед стартом
│   ├── db/
│   │   ├── models.py              # SQLAlchemy ORM models
│   │   ├── session.py             # async engine + sessionmaker
│   │   └── repositories/          # CRUD методы (Repository pattern)
│   │       ├── product_repo.py
│   │       ├── price_repo.py
│   │       └── alert_repo.py
│   ├── services/
│   │   ├── price_service.py       # бизнес-логика цен
│   │   ├── currency_service.py    # конвертация + НБУ
│   │   ├── alert_service.py       # алерты
│   │   └── fetcher_service.py     # сбор цен из магазинов
│   ├── shop_adapters/
│   │   ├── base.py                # BaseShopAdapter ABC
│   │   ├── dummyjson.py           # DummyJsonAdapter
│   │   ├── fakestore.py           # FakeStoreAdapter
│   │   └── registry.py            # ADAPTERS dict + get_adapter()
│   ├── schemas/                   # Pydantic schemas (request/response)
│   │   ├── product.py
│   │   ├── price.py
│   │   └── alert.py
│   ├── tasks/
│   │   ├── celery_app.py          # Celery instance + beat_schedule со всеми задачами
│   │   ├── prices.py              # fetch_prices_task + create_price_history_partition_task
│   │   ├── rates.py               # sync_exchange_rates_task
│   │   ├── alerts.py              # check_price_alerts_task
│   │   └── seed.py                # seed_shops(), seed_products()
│   └── main.py                    # FastAPI app factory + lifespan (auto-seed)
├── alembic/                       # Миграции БД
├── scripts/
│   └── generate_token.py          # генерация JWT для тестирования API
├── tests/
│   ├── unit/                      # Тесты сервисов и адаптеров
│   └── integration/               # Тесты API (httpx + pytest)
├── docker-compose.yml
├── Dockerfile
├── .env.example               # шаблон конфига, коммитится в репо
├── .env                       # реальный конфиг, в .gitignore
├── pyproject.toml             # зависимости + настройки ruff/mypy/pytest
└── uv.lock                    # lock-файл, коммитится в репо
```

---

## 10. Решения «до уточнения»

| Вопрос | Текущее решение / статус |
|---|---|
| Дедупликация алертов | Алерт деактивируется после первого срабатывания. Нужно уточнить: повторно активировать автоматически или только вручную? |
| Маппинг товаров между магазинами | Маппинг по индексу при инициализации (`seed_products`). Первые 20 товаров получают цены из двух магазинов, остальные — только из DummyJSON. В production заменяется на fuzzy-matching. |
| Частота опроса магазинов | Текущий выбор — каждые 4 часа. Нужно ли настраивать per-shop? |
| Rate limiting внешних API | DummyJSON и FakeStore могут ограничивать запросы. Нужна retry-стратегия с exponential backoff. |
| Email-провайдер | SMTP для dev, SendGrid / AWS SES для production — финальный выбор зависит от инфраструктуры. |
| Авторизация | Статический JWT без срока действия. Токен генерируется один раз через `scripts/generate_token.py`, проверяется в каждом запросе через `verify_token` в `deps.py`. В production заменяется на JWT с `exp` + refresh. |

---

## 11. Последовательность: сбор цен

Упрощённая схема работы фоновой задачи:

```
Celery Beat
   │
   └─► fetch_prices_task()
         │
         └─► PriceFetcherService.fetch_all_shops()
               │
               └─► [для каждого Shop в БД, параллельно через asyncio.gather()]
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

## 12. Конфигурация приложения

Все настройки хранятся в `.env` файле и читаются через `pydantic-settings`. Валидация происходит при старте — если обязательная переменная не задана, приложение падает сразу с понятной ошибкой, а не в рантайме.

### 12.1 app/core/config.py

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import PostgresDsn, RedisDsn

class Settings(BaseSettings):
    # ── Приложение ──────────────────────────────────────────
    app_env: str = "dev"                  # dev | prod
    app_secret_key: str                   # для подписи JWT
    debug: bool = False
    run_seed_on_startup: bool = False     # true только для api контейнера

    # ── База данных ─────────────────────────────────────────
    database_url: PostgresDsn             # postgresql+asyncpg://...
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # ── Redis ───────────────────────────────────────────────
    redis_url: RedisDsn                   # redis://redis:6379/0
    redis_ttl_exchange_rate: int = 3600   # секунд — текущий курс
    redis_ttl_product_prices: int = 3600  # секунд — агрег. цены
    redis_ttl_user_products: int = 300    # секунд — список товаров

    # ── Celery ──────────────────────────────────────────────
    celery_broker_url: RedisDsn           # redis://redis:6379/1
    celery_result_backend: RedisDsn       # redis://redis:6379/2
    fetch_prices_interval_hours: int = 4
    check_alerts_interval_minutes: int = 60
    sync_rates_cron_hour: int = 8         # время UTC для синхронизации курсов

    # ── Email ───────────────────────────────────────────────
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str
    smtp_from: str = "noreply@pricetracker.com"
    smtp_use_tls: bool = True

    # ── НБУ API ─────────────────────────────────────────────
    nbu_api_url: str = "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange"
    nbu_historical_years: int = 5         # сколько лет истории загружать при init

    # ── Внешние API магазинов ────────────────────────────────
    dummyjson_url: str = "https://dummyjson.com"
    fakestore_url: str = "https://fakestoreapi.com"
    shop_api_timeout: int = 10            # секунд — таймаут запроса к магазину
    shop_api_retry_attempts: int = 3      # попыток при ошибке

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

settings = Settings()
```

### 12.2 .env.example

Файл `.env.example` коммитится в репозиторий как шаблон. Реальный `.env` добавлен в `.gitignore`.

```dotenv
# ── Приложение ──────────────────────────────────────────────
APP_ENV=dev
APP_SECRET_KEY=change-me-in-production
DEBUG=true
RUN_SEED_ON_STARTUP=false   # переопределяется в docker-compose для api

# ── База данных ─────────────────────────────────────────────
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

# ── НБУ API ─────────────────────────────────────────────────
NBU_HISTORICAL_YEARS=5

# ── Магазины ─────────────────────────────────────────────────
DUMMYJSON_URL=https://dummyjson.com
FAKESTORE_URL=https://fakestoreapi.com
SHOP_API_TIMEOUT=10
SHOP_API_RETRY_ATTEMPTS=3
```

### 12.3 Разные окружения

| Файл | Окружение | Используется |
|---|---|---|
| `.env` | локальная разработка | по умолчанию |
| `.env.prod` | production | `env_file=".env.prod"` или переменные среды хоста |

В production переменные окружения передаются напрямую через хостовую среду или секреты (Docker Secrets, Vault) — `.env` файл на сервере не хранится.

### 12.4 Авторизация — JWT без срока действия

Авторизация реализована минимально: один статический JWT-токен, который проверяется в каждом запросе. Без регистрации, без логина, без refresh-токенов.

**app/core/security.py**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_token(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.app_secret_key,
            algorithms=["HS256"],
        )
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

**Генерация токена — один раз при настройке проекта:**

```python
# scripts/generate_token.py
import jwt
from app.core.config import settings

token = jwt.encode(
    {"sub": "admin", "role": "admin"},
    settings.app_secret_key,
    algorithm="HS256",
)
print(f"Bearer {token}")
```

```bash
# Запуск:
uv run python scripts/generate_token.py
# Вывод: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

Полученный токен вставляется в Swagger UI (кнопка "Authorize") или в заголовок запроса:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**Использование в эндпоинтах через `deps.py`:**

```python
# app/api/deps.py
from app.core.security import verify_token

# Зависимость — добавляется в любой эндпоинт где нужна авторизация
CurrentUser = Annotated[dict, Depends(verify_token)]
```

```python
# app/api/v1/products.py
@router.get("/products")
async def get_products(
    user: CurrentUser,          # проверяет токен
    currency: str = "USD",
    service: PriceService = Depends(get_price_service),
):
    return await service.get_products_list(currency=currency)
```

> **Почему без `exp`:** для ТЗ срок действия токена не нужен — токен генерируется один раз и используется для тестирования API. В production добавляется `exp` и refresh-механизм.



### 13.1 pyproject.toml

Единый файл для зависимостей, dev-зависимостей и настроек инструментов. Коммитится вместе с `uv.lock`.

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

# Копируем UV из официального образа — не нужно устанавливать через pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Копируем только файлы зависимостей — этот слой кешируется
# и не пересобирается при изменении кода приложения
COPY pyproject.toml uv.lock ./

# --frozen     — строго из lock-файла, без обновлений
# --no-dev     — только prod зависимости
# --no-cache   — не хранить кеш в образе
RUN uv sync --frozen --no-dev --no-cache

COPY . .

# Используется как базовый образ для api, worker, beat и migrate
```

### 13.3 app/core/wait_for_db.py

`healthcheck` гарантирует что postgres принимает соединения, но в первые секунды база может быть ещё не полностью готова. Этот скрипт явно проверяет доступность через реальный SQL-запрос перед стартом приложения — без лишних зависимостей, на чистом Python.

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

> `beat` не использует скрипт — он не обращается к БД напрямую и зависит только от `worker`.

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

  # ── FastAPI приложение ───────────────────────────────────
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
      RUN_SEED_ON_STARTUP: "true"   # seed запускается только здесь
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

  # ── Celery Beat (планировщик) ────────────────────────────
  beat:
    build: .
    command: celery -A app.tasks.celery_app beat --loglevel=info --scheduler celery.beat.PersistentScheduler
    restart: unless-stopped
    env_file: .env
    environment:
      RUN_SEED_ON_STARTUP: "false"
    depends_on:
      - worker

  # ── Миграции (запускается один раз и завершается) ────────
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

### 13.5 Порядок первого запуска

```bash
# 1. Скопировать конфиг
cp .env.example .env
# отредактировать .env — минимум задать SMTP_* и APP_SECRET_KEY

# 2. Собрать образы и запустить инфраструктуру
docker compose up -d postgres redis

# 3. Применить миграции
docker compose run --rm migrate

# 4. Запустить всё — seed запустится автоматически внутри api (lifespan)
docker compose up -d

# Проверить что seed отработал
docker compose logs api | grep -i seed
# Ожидаемый вывод:
# INFO: First run detected, seeding database...
# INFO: Seed completed successfully.

# Проверить статус всех контейнеров
docker compose ps
```

> **Seed запускается автоматически** через FastAPI `lifespan` при старте `api` контейнера. При повторных рестартах проверяет что БД уже заполнена и пропускает (см. раздел 5.8).

### 13.6 Полезные команды

```bash
# ── UV (локальная разработка) ────────────────────────────────
# Установить все зависимости включая dev
uv sync

# Добавить новую зависимость
uv add httpx

# Добавить dev-зависимость
uv add --dev pytest-asyncio

# Обновить lock-файл
uv lock --upgrade

# Запустить команду в окружении проекта
uv run pytest
uv run alembic upgrade head

# ── Docker ───────────────────────────────────────────────────
# Перезапустить только API без пересборки
docker compose restart api

# Посмотреть очередь Celery
docker compose exec worker celery -A app.tasks.celery_app inspect active

# Подключиться к PostgreSQL
docker compose exec postgres psql -U postgres price_tracker

# Применить новую миграцию
docker compose run --rm migrate

# Остановить всё и удалить volumes (полный сброс)
docker compose down -v
```


---

*Price Tracker Service — Архитектурный документ v1.0*
