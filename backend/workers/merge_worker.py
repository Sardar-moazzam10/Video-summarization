"""
Dedicated ARQ Redis worker for VidFusion video summarization and merge jobs.

Run with:
    arq backend.workers.merge_worker.WorkerSettings
Or:
    python -m backend.workers.merge_worker
"""
import asyncio
import logging
import os
import sys

from ..core.config import get_settings
from ..core.database import get_database, close_database
from ..core.redis_queue import get_redis_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (MergeWorker) %(message)s",
)
logger = logging.getLogger("merge_worker")
settings = get_settings()


async def run_merge_job(ctx, job_id: str):
    """
    ARQ worker function to execute a video merge and summarization pipeline.
    """
    logger.info("Worker received merge job: %s", job_id)
    from ..api.merge import process_merge_job

    try:
        await process_merge_job(job_id, is_worker=True)
        logger.info("Worker completed merge job: %s", job_id)
    except Exception as exc:
        logger.error("Worker failed while processing job %s: %s", job_id, exc, exc_info=True)
        raise exc


async def startup(ctx):
    """
    Worker startup hook: Connects to MongoDB and pre-loads/warms ML models.
    """
    logger.info("Initializing Merge Worker database connection...")
    db = await get_database()
    logger.info("Database connection established for database: %s", db.name)

    # Optional model warm-up so the first queued job has zero cold-start delay
    try:
        from ..services.summarization_service import _get_pipeline
        _get_pipeline()
        logger.info("BART summarization model warmed up in worker process.")
    except Exception as exc:
        logger.warning("Could not pre-warm summarization model in worker: %s", exc)

    try:
        from ..services.fusion_engine import get_sentence_transformer
        get_sentence_transformer()
        logger.info("Sentence-BERT embedding model warmed up in worker process.")
    except Exception as exc:
        logger.warning("Could not pre-warm embedding model in worker: %s", exc)

    logger.info("Merge Worker is ready and listening for jobs from Redis...")


async def shutdown(ctx):
    """
    Worker shutdown hook: Safely close database connections.
    """
    logger.info("Shutting down Merge Worker...")
    await close_database()
    logger.info("Merge Worker shutdown completed.")


class WorkerSettings:
    """
    ARQ worker configuration.
    """
    functions = [run_merge_job]
    redis_settings = get_redis_settings()
    max_jobs = 2          # Strict concurrency limit: max 2 simultaneous video pipelines to protect CPU/RAM
    job_timeout = 1800   # 30 minutes max execution time per video merge job
    keep_result = 3600   # Retain completed job status in Redis for 1 hour
    on_startup = startup
    on_shutdown = shutdown


if __name__ == "__main__":
    from arq import run_worker
    run_worker(WorkerSettings)
