import redis.asyncio as aioredis

from app.core.config import settings

# Единый Redis-клиент приложения. Пул соединений внутри клиента переиспользуется,
# поэтому держим его модульным синглтоном, а не создаём в каждом сервисе.
redis_client: aioredis.Redis = aioredis.Redis.from_url(
    str(settings.redis_url), decode_responses=True
)
