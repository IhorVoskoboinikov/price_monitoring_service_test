FROM python:3.12-slim

# Copy UV from the official image — no need to install it via pip
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only the dependency files — this layer is cached
# and is not rebuilt when the app code changes
COPY pyproject.toml uv.lock ./

# --frozen     — strictly from the lock file, no updates
# --no-dev     — prod dependencies only
# --no-cache   — do not keep a cache in the image
RUN uv sync --frozen --no-dev --no-cache

# Add the venv to PATH — lets you call python/uvicorn/celery/alembic directly
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

# Used as the base image for api, worker, beat, and migrate
