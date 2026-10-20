"""Deterministic recovery for process-local merge workers."""
from datetime import datetime, timedelta
from ..models.job import JobStatus

NON_TERMINAL = [
    JobStatus.PENDING.value, JobStatus.TRANSCRIBING.value,
    JobStatus.ANALYZING.value, JobStatus.FUSING.value,
    JobStatus.SUMMARIZING.value, JobStatus.ENRICHING.value,
    JobStatus.GENERATING_VOICE.value, JobStatus.GENERATING_VIDEO.value,
    JobStatus.VIDEO_READY.value,
]

async def recover_orphaned_jobs(jobs_collection) -> dict:
    """Resolve process-local workers without disturbing durable output workers.

    Jobs explicitly handed to the Mongo-backed output queue survive an API
    process restart.  Their worker leases are recovered separately by
    ``recover_expired_output_tasks`` and must never be converted to an error
    merely because the API process restarted.
    """
    now = datetime.utcnow()
    process_local_only = {"output_execution_mode": {"$ne": "durable_workers"}}
    preserved = await jobs_collection.update_many(
        {
            "status": JobStatus.VIDEO_READY.value,
            "video_path": {"$nin": [None, ""]},
            **process_local_only,
        },
        {"$set": {
            "status": JobStatus.PARTIAL_SUCCESS.value,
            "progress_percent": 100,
            "stage_message": "Video recovered; summary worker was interrupted. Retry is available.",
            "warning": "Backend restarted after the rendered-video checkpoint; written summary may be incomplete.",
            "recovery_state": "render_checkpoint_preserved", "recoverable": True,
            "completed_at": now, "updated_at": now,
            "evaluation_state": "unavailable",
            "evaluation_error": "Written-summary worker was interrupted before evaluation.",
            "evaluation_updated_at": now,
        }},
    )
    failed = await jobs_collection.update_many(
        {
            "status": {"$in": [s for s in NON_TERMINAL if s != JobStatus.VIDEO_READY.value]},
            **process_local_only,
        },
        {"$set": {
            "status": JobStatus.ERROR.value,
            "stage_message": "Processing was interrupted by a backend restart. This job can be retried.",
            "error": "WORKER_INTERRUPTED: backend restarted before a safe resumable checkpoint",
            "recovery_state": "recoverable_failure", "recoverable": True,
            "completed_at": now, "updated_at": now,
            "evaluation_state": "unavailable",
            "evaluation_error": "Job did not reach a completed summary.",
            "evaluation_updated_at": now,
        }},
    )

    try:
        from .storage_hygiene import cleanup_temp_scratch, cleanup_download_scratch
        cleanup_temp_scratch()
        cleanup_download_scratch()
    except Exception as e:
        print(f"[WARN] Orphan disk artifact cleanup: {e}")

    return {"render_checkpoints_preserved": preserved.modified_count,
            "recoverable_failures": failed.modified_count}


def heartbeat_is_stale(value, *, now=None, stale_after_seconds=120):
    """Pure helper used by monitoring/tests; missing heartbeat is stale."""
    now = now or datetime.utcnow()
    if value is None:
        return True
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return True
    return now - value > timedelta(seconds=stale_after_seconds)
