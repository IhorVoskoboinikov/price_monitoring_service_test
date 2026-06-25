import redis.asyncio as aioredis

from app.core.config import settings


def create_redis_client() -> aioredis.Redis:
    """Новый Redis-клиент. Для Celery-задач (asyncio.run создаёт новый event loop
    на каждый вызов) нужен клиент, привязанный к текущему loop'у, — его создают
    этим хелпером и закрывают после задачи."""
    return aioredis.Redis.from_url(str(settings.redis_url), decode_responses=True)


# Единый Redis-клиент приложения (FastAPI работает в одном event loop). Пул
# соединений внутри клиента переиспользуется, поэтому держим его синглтоном.
redis_client: aioredis.Redis = create_redis_client()
