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

# Добавляем venv в PATH — позволяет вызывать python/uvicorn/celery/alembic напрямую
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

# Используется как базовый образ для api, worker, beat и migrate
