import redis.asyncio as aioredis

from app.core.config import settings


def create_redis_client() -> aioredis.Redis:
    """New Redis client. Celery tasks use asyncio.run, which makes a new event loop
    on each call, so they need a client bound to the current loop: create it with
    this helper and close it after the task."""
    return aioredis.Redis.from_url(str(settings.redis_url), decode_responses=True)


# One shared Redis client for the app (FastAPI runs in a single event loop). The
# connection pool inside the client is reused, so we keep it as a singleton.
redis_client: aioredis.Redis = create_redis_client()
