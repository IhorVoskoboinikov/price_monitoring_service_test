# Price Tracker Service

Backend-сервис на FastAPI для отслеживания динамики цен на товары из нескольких
магазинов (DummyJSON, FakeStore), с историей цен, конвертацией валют по курсам НБУ
и email-уведомлениями при падении цены ниже порога.

Тестовое задание (Middle+ / Senior Python Developer). Подробное архитектурное
описание — в [`price_tracker_architecture.md`](price_tracker_architecture.md).

## Возможности

- Список отслеживаемых товаров с диапазоном цен и трендом (рост/падение/без
  изменений vs средняя за 30 дней), сортировка по цене и тренду.
- Карточка товара: описание, диапазон цен, число магазинов.
- Все цены по магазинам на сегодня и история цен по дням (серия на каждый
  магазин + средняя), с конвертацией каждой точки по курсу её даты.
- Watchlist пользователя (добавить/удалить/список).
- Алерты: email при снижении цены ниже указанного порога (порог в любой валюте,
  хранится в USD).
- Выбор валюты (`USD`/`UAH`/`EUR`/`GBP`) везде, где возвращаются цены.

## Технологии

Python 3.12 · FastAPI · SQLAlchemy 2 (async) + Alembic · PostgreSQL 16
(партиционирование истории цен) · Redis (кеш курсов) · Celery + Beat · httpx ·
Pydantic v2 · uv · Docker Compose.

## Архитектура (кратко)

```
API (FastAPI)  ->  Services (бизнес-логика)  ->  Repositories  ->  PostgreSQL
                     CurrencyService  ->  Redis / НБУ API
                     ShopAdapters     ->  DummyJSON / FakeStore
Celery Beat  ->  задачи (сбор цен, проверка алертов, синхр. курсов, партиции)
```

- **Repository-per-entity + DI**: эндпоинты получают сервисы через
  `Depends` (`app/api/deps.py`), сервисы — репозитории. Транзакция на запрос
  открывается в `_get_db` (commit при успехе, rollback при ошибке).
- **Адаптеры магазинов** изолированы за `BaseShopAdapter`; новый магазин — это
  новый класс + строка в реестре, бизнес-логика не меняется.
- **Цены хранятся только в USD**; конвертация — на лету через `ExchangeRate`
  (гривна как опорная валюта).

## Быстрый старт (Docker Compose)

```bash
# 1. Конфиг (единственный обязательный шаг)
cp .env.example .env
# отредактируйте .env: как минимум APP_SECRET_KEY.
# Для реальной отправки писем — EMAIL_ENABLED=true и рабочие SMTP_* (см. ниже).

# 2. Поднять весь стек одной командой
docker compose up -d --build

# 3. Наблюдать старт и автоматический seed
docker compose logs -f api
```

`docker compose` сам выстраивает порядок: `postgres`/`redis` (healthcheck) →
`migrate` (`alembic upgrade head`, ждём успешного завершения через
`depends_on: condition: service_completed_successfully`) → `api`/`worker` →
`beat`. Отдельно поднимать инфраструктуру и гонять миграции не нужно.

API: <http://localhost:8000>, Swagger: <http://localhost:8000/docs>.

> При старте `api` через FastAPI lifespan наполняет БД (магазины, товары из обоих
> API, сегодняшние курсы). Шаги идемпотентны: магазины/товары создаются один раз,
> курсы синхронизируются на каждом старте.
>
> Миграции можно при желании запускать отдельно (например, в CI):
> `docker compose run --rm migrate`.

## Авторизация

Все эндпоинты требуют Bearer JWT (статический токен — полноценный auth вне ТЗ).
Сгенерировать токен демо-пользователя:

```bash
uv run python scripts/generate_token.py
# Bearer eyJhbGciOiJIUzI1NiI...
```

Вставьте его в Swagger («Authorize») или в заголовок:

```bash
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/v1/products
```

## Основные эндпоинты

| Метод + URL | Назначение |
|---|---|
| `GET /api/v1/products?currency=&sort=` | Список отслеживаемых товаров с трендом |
| `GET /api/v1/products/{id}?currency=` | Карточка товара |
| `GET /api/v1/products/{id}/prices` | Цены по магазинам на сегодня |
| `GET /api/v1/products/{id}/price-history` | История цен (серии + средняя) |
| `GET/POST /api/v1/me/products` · `DELETE /api/v1/me/products/{id}` | Watchlist |
| `GET/POST /api/v1/me/alerts` · `DELETE /api/v1/me/alerts/{id}` | Алерты |
| `GET /api/v1/currencies` | Текущие курсы валют |
| `GET /api/v1/health` | Health-check |

## Email-уведомления

По умолчанию `EMAIL_ENABLED=false` — **console-режим**: письма не отправляются,
а логируются (удобно для разработки и проверки логики алертов). Для реальной
доставки задайте `EMAIL_ENABLED=true` и рабочие `SMTP_*` в `.env`
(Gmail App Password или Mailtrap — см. комментарии в `.env.example`).

## Курсы валют

Источник — официальное API НБУ (бесплатное, без ключа). `get_rate` идёт по
цепочке Redis → PostgreSQL → НБУ (on-demand с записью в БД) → ближайший
предыдущий курс (fallback). Сегодняшние курсы синхронизируются Celery-задачей;
исторические можно догрузить вручную:

```bash
uv run python scripts/sync_historical_rates.py 30   # за последние 30 дней
```

## Тесты

Тесты гоняются на реальном PostgreSQL в Docker через `testcontainers` (тот же
диалект, что в проде — честно проверяются UUID, on-conflict upsert, оконные
функции и партиционирование). Redis замокан `fakeredis`, внешние API (НБУ,
магазины) — фейковым httpx-клиентом, сеть не используется.

```bash
uv run python tests/run.py          # весь набор + отчёт покрытия
uv run python tests/run.py -k alert # фильтр по имени
```

`tests/run.py` запускает pytest с покрытием (term + HTML в `tests/htmlcov`).
Требуется запущенный Docker (для testcontainers).

## Локальная разработка

```bash
uv sync                      # установить зависимости (включая dev)
uv run ruff check app/       # линт
uv run alembic upgrade head  # миграции
```

## Конфигурация

Все настройки — в `.env` (читаются через `pydantic-settings`, валидация при
старте). Шаблон со всеми переменными и комментариями — в `.env.example`.
Реальный `.env` в `.gitignore` и в репозиторий не попадает.

## Заметки по решениям

- **Маппинг товаров между магазинами** — по индексу при seed (первые ~20 товаров
  получают цены из двух магазинов). В production заменяется на fuzzy-matching без
  изменения схемы БД.
- **Дедуп цен** — повторный снимок цены товара в пределах 1 часа не пишется.
- **Историческая загрузка курсов за 5 лет** — вынесена в скрипт
  (`sync_historical_rates.py`), чтобы не задерживать старт; при необходимости
  легко перевести в фоновую задачу первого запуска.
