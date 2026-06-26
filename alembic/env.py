import asyncio
import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Load .env — a no-op if the vars are already in the environment (Docker container)
load_dotenv()

from app.db.models import Base  # noqa: E402 — after load_dotenv  # imports all models via __init__.py

config = context.config

# DATABASE_URL comes from the environment:
#   - In Docker: passed via env_file in docker-compose
#   - Locally: from the .env file (load_dotenv above)
#     To run alembic locally, postgres must be reachable on localhost:5432
#     (the port is published in docker-compose). Change @postgres to @localhost in
#     .env, or pass the variable directly:
#       DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/price_tracker \
#         alembic upgrade head
database_url = os.environ["DATABASE_URL"]
config.set_main_option("sqlalchemy.url", database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
