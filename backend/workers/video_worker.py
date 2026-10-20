"""Dedicated manifest-consuming video worker.

Run with: ``python -m backend.workers.video_worker``.
"""

import asyncio
from datetime import datetime
import os
import shutil
import socket

from ..core.database import get_database
from ..models.output_contracts import EvidenceManifest
from ..services.output_task_queue import (
    claim_output_task,
    finish_output_task,
    maintain_output_task_lease,
    reconcile_job_output_status,
)
from ..services.rights_service import freeze_job_rights_snapshot
from ..services.video_service import get_video_service


WORKER_ID = f"video:{socket.gethostname()}:{os.getpid()}"


async def _set_component(jobs, job_id, *, status, stage, progress, attempts, error=None):
    await jobs.update_one(
        {"job_id": job_id},
        {"$set": {"video_component": {
            "status": status,
            "stage": stage,
            "progress_percent": progress,
            "attempts": attempts,
            "error": error,
            "updated_at": datetime.utcnow(),
        }}},
    )


async def process_one(database) -> bool:
    lease_seconds = 1800
    task = await claim_output_task(
        database, output_type="video", worker_id=WORKER_ID, lease_seconds=lease_seconds,
    )
    if not task:
        return False
    task_id = task["task_id"]
    job_id = task["job_id"]
    jobs = database["jobs"]
    download_dir = os.path.join("audio_cache", "video_downloads", job_id)
    lease_stop = asyncio.Event()
    lease_task = asyncio.create_task(maintain_output_task_lease(
        database,
        task_id=task_id,
        worker_id=WORKER_ID,
        stop_event=lease_stop,
        lease_seconds=lease_seconds,
    ))
    try:
        job = await jobs.find_one({"job_id": job_id})
        if not job or not job.get("evidence_manifest"):
            raise ValueError("job has no published evidence manifest")
        manifest = EvidenceManifest.model_validate(job["evidence_manifest"])
        if manifest.manifest_version != task["manifest_version"]:
            raise ValueError("task manifest version no longer matches job")
        if not manifest.segments:
            raise ValueError("manifest contains no renderable segments")

        await _set_component(
            jobs, job_id, status="running", stage="downloading", progress=10,
            attempts=task["attempts"],
        )
        service = get_video_service()
        source_ids = list(dict.fromkeys(segment.video_id for segment in manifest.segments))
        total_duration = sum(
            source.duration_seconds or 0.0 for source in manifest.sources
            if source.video_id in source_ids
        )

        async def progress(message: str):
            stage = "rendering" if "Cutting" in message or "Stitching" in message else "downloading"
            percent = 60 if stage == "rendering" else 25
            await _set_component(
                jobs, job_id, status="running", stage=stage, progress=percent,
                attempts=task["attempts"],
            )

        paths = await service.download_videos(
            source_ids,
            job_id=job_id,
            progress_callback=progress,
            source_duration_seconds=total_duration,
        )
        missing = [source for source in source_ids if source not in paths]
        if missing:
            raise RuntimeError(f"selected source media unavailable: {', '.join(missing)}")

        clips = [segment.model_dump() for segment in manifest.segments]
        video_path = await service.generate_highlight_reel(
            job_id=job_id,
            highlight_segments=clips,
            video_paths=paths,
            audio_path=None,
            progress_callback=progress,
        )
        if not video_path:
            raise RuntimeError("renderer did not publish an output path")
        if lease_task.done() and lease_task.result() is False:
            raise RuntimeError("video worker lost task lease before publication")

        # Rights are frozen before the media path and READY state become visible.
        await freeze_job_rights_snapshot(
            jobs_collection=jobs,
            job_id=job_id,
            user_id=job.get("user_id") or "anonymous",
            video_ids=source_ids,
            db=database,
        )
        now = datetime.utcnow()
        published = await jobs.update_one(
            {"job_id": job_id, "evidence_manifest.manifest_version": task["manifest_version"]},
            {"$set": {
                "video_path": video_path,
                "highlight_segments": clips,
                "has_video_ready": True,
                "video_component": {
                    "status": "ready", "stage": "ready", "progress_percent": 100,
                    "attempts": task["attempts"], "error": None, "updated_at": now,
                },
            }},
        )
        if published.modified_count != 1:
            raise RuntimeError("video output was not published because the manifest changed")
        await reconcile_job_output_status(database, job_id)
        await finish_output_task(
            database, task_id=task_id, worker_id=WORKER_ID, succeeded=True,
        )
    except Exception as exc:
        if lease_task.done() and lease_task.result() is False:
            return True
        await finish_output_task(
            database, task_id=task_id, worker_id=WORKER_ID,
            succeeded=False, error=str(exc),
        )
        current_task = await database["output_tasks"].find_one({"task_id": task_id})
        queued = (current_task or {}).get("status") == "queued"
        await _set_component(
            jobs, job_id,
            status="queued" if queued else "failed",
            stage="retry_queued" if queued else "failed",
            progress=0 if queued else 100,
            attempts=task.get("attempts", 1),
            error=str(exc),
        )
        await reconcile_job_output_status(database, job_id)
    finally:
        lease_stop.set()
        await lease_task
        if os.path.isdir(download_dir):
            shutil.rmtree(download_dir, ignore_errors=True)
    return True


async def run_forever(poll_seconds: float = 1.0):
    database = await get_database()
    while True:
        worked = await process_one(database)
        if not worked:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(run_forever())
