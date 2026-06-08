"""Redis connection helper."""

import os
import logging
import redis

logger = logging.getLogger(__name__)

_redis_client = None


def get_redis() -> redis.Redis:
    """Get a shared Redis client (singleton)."""
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _redis_client = redis.from_url(redis_url, decode_responses=True)
        # Quick health check
        _redis_client.ping()
        logger.info(f"Redis connected: {redis_url}")
    return _redis_client
