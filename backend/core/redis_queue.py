"""
Redis Queue Manager for VidFusion using ARQ.

Provides connection pooling, enqueueing, and health checks for background AI/merge jobs.
"""
import logging
from typing import Optional
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from .config import get_settings

logger = logging.getLogger("redis_queue")
settings = get_settings()

_redis_pool: Optional[ArqRedis] = None


def get_redis_settings() -> RedisSettings:
    """Return ARQ RedisSettings based on application configuration."""
    return RedisSettings(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        database=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD or None,
    )


async def init_redis_pool() -> Optional[ArqRedis]:
    """Initialize the shared ARQ Redis connection pool."""
    global _redis_pool
    if not settings.REDIS_QUEUE_ENABLED:
        logger.info("Redis queue is disabled by configuration (REDIS_QUEUE_ENABLED=False).")
        return None

    try:
        redis_settings = get_redis_settings()
        _redis_pool = await create_pool(redis_settings)
        # Test ping
        await _redis_pool.ping()
        logger.info("Connected to Redis Queue at %s:%s (db=%s)", settings.REDIS_HOST, settings.REDIS_PORT, settings.REDIS_DB)
        return _redis_pool
    except Exception as exc:
        logger.warning("Could not initialize Redis Queue pool: %s. Background jobs will fallback to in-memory processing.", exc)
        _redis_pool = None
        return None


async def get_redis_pool() -> Optional[ArqRedis]:
    """Get the active Redis connection pool, reconnecting if needed."""
    global _redis_pool
    if _redis_pool is None and settings.REDIS_QUEUE_ENABLED:
        return await init_redis_pool()
    return _redis_pool


async def close_redis_pool() -> None:
    """Safely close the Redis connection pool."""
    global _redis_pool
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
            logger.info("Redis Queue pool closed gracefully.")
        except Exception as exc:
            logger.warning("Error closing Redis pool: %s", exc)
        finally:
            _redis_pool = None


async def enqueue_merge_job(job_id: str) -> bool:
    """
    Enqueue a merge job into the ARQ Redis worker queue.
    Returns True if successfully enqueued, False otherwise.
    """
    pool = await get_redis_pool()
    if pool is None:
        return False

    try:
        # Pass _job_id to ensure idempotency (no duplicate execution of same job_id)
        job = await pool.enqueue_job("run_merge_job", job_id, _job_id=job_id)
        if job:
            logger.info("Job %s successfully enqueued to Redis (arq_id=%s)", job_id, job.job_id)
            return True
        else:
            logger.warning("Job %s was already enqueued in Redis queue.", job_id)
            return True
    except Exception as exc:
        logger.error("Failed to enqueue job %s to Redis queue: %s", job_id, exc)
        return False

