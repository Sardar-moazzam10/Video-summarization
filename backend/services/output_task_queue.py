"""Durable Mongo-backed queue for isolated output workers."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
import asyncio
import uuid

from pymongo import ASCENDING, ReturnDocument


TASK_COLLECTION = "output_tasks"
TERMINAL_STATES = {"completed", "failed", "cancelled"}


async def ensure_output_task_indexes(database) -> None:
    collection = database[TASK_COLLECTION]
    await collection.create_index(
        [("job_id", ASCENDING), ("manifest_version", ASCENDING),
         ("output_type", ASCENDING), ("worker_version", ASCENDING)],
        unique=True,
        name="unique_output_task",
    )
    await collection.create_index(
        [("status", ASCENDING), ("lease_expires_at", ASCENDING),
         ("created_at", ASCENDING)],
        name="claimable_output_tasks",
    )


async def enqueue_output_task(
    database,
    *,
    job_id: str,
    manifest_version: int,
    output_type: str,
    worker_version: str = "v1",
    max_attempts: int = 3,
    initial_status: str = "queued",
) -> dict:
    if output_type not in {"video", "text"}:
        raise ValueError("output_type must be video or text")
    now = datetime.utcnow()
    identity = {
        "job_id": job_id,
        "manifest_version": manifest_version,
        "output_type": output_type,
        "worker_version": worker_version,
    }
    await database[TASK_COLLECTION].update_one(
        identity,
        {"$setOnInsert": {
            **identity,
            "task_id": str(uuid.uuid4()),
            "status": initial_status,
            "attempts": 0,
            "max_attempts": max_attempts,
            "created_at": now,
            "updated_at": now,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error": None,
        }},
        upsert=True,
    )
    return await database[TASK_COLLECTION].find_one(identity)


async def activate_output_tasks(database, *, job_id: str, manifest_version: int) -> int:
    """Atomically release a complete set of held sibling tasks to workers."""
    result = await database[TASK_COLLECTION].update_many(
        {"job_id": job_id, "manifest_version": manifest_version, "status": "held"},
        {"$set": {"status": "queued", "updated_at": datetime.utcnow()}},
    )
    return result.modified_count


async def cancel_held_output_tasks(database, *, job_id: str, manifest_version: int) -> int:
    result = await database[TASK_COLLECTION].update_many(
        {"job_id": job_id, "manifest_version": manifest_version, "status": "held"},
        {"$set": {
            "status": "cancelled",
            "last_error": "Sibling output dispatch did not complete.",
            "updated_at": datetime.utcnow(),
        }},
    )
    return result.modified_count


async def claim_output_task(
    database,
    *,
    output_type: str,
    worker_id: str,
    lease_seconds: int = 120,
) -> Optional[dict]:
    now = datetime.utcnow()
    return await database[TASK_COLLECTION].find_one_and_update(
        {
            "output_type": output_type,
            "$expr": {"$lt": ["$attempts", "$max_attempts"]},
            "$or": [
                {"status": "queued"},
                {"status": "running", "lease_expires_at": {"$lte": now}},
            ],
        },
        {"$set": {
            "status": "running",
            "lease_owner": worker_id,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "updated_at": now,
        }, "$inc": {"attempts": 1}},
        sort=[("created_at", ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )


async def heartbeat_output_task(
    database, task_id: str, worker_id: str, lease_seconds: int = 120,
) -> bool:
    now = datetime.utcnow()
    result = await database[TASK_COLLECTION].update_one(
        {"task_id": task_id, "status": "running", "lease_owner": worker_id},
        {"$set": {
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "updated_at": now,
        }},
    )
    return result.modified_count == 1


async def maintain_output_task_lease(
    database,
    *,
    task_id: str,
    worker_id: str,
    stop_event: asyncio.Event,
    lease_seconds: int,
) -> bool:
    """Renew ownership until stopped; return False if ownership is lost."""
    interval = max(0.05, lease_seconds / 3.0)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break
        except asyncio.TimeoutError:
            try:
                owned = await heartbeat_output_task(
                    database, task_id, worker_id, lease_seconds=lease_seconds
                )
            except Exception:
                return False
            if not owned:
                return False
    return True


async def requeue_output_task(
    database,
    *,
    job_id: str,
    manifest_version: int,
    output_type: str,
    worker_version: str = "v1",
) -> Optional[dict]:
    """Explicit user retry. Never mutates a currently leased/running task."""
    now = datetime.utcnow()
    identity = {
        "job_id": job_id,
        "manifest_version": manifest_version,
        "output_type": output_type,
        "worker_version": worker_version,
    }
    result = await database[TASK_COLLECTION].update_one(
        {**identity, "status": {"$in": ["failed", "cancelled", "completed"]}},
        {"$set": {
            "status": "queued",
            "attempts": 0,
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error": None,
            "updated_at": now,
        }, "$unset": {"completed_at": ""}},
    )
    if result.modified_count:
        return await database[TASK_COLLECTION].find_one(identity)
    existing = await database[TASK_COLLECTION].find_one(identity)
    if existing:
        return None
    return await enqueue_output_task(
        database,
        job_id=job_id,
        manifest_version=manifest_version,
        output_type=output_type,
        worker_version=worker_version,
    )


async def recover_expired_output_tasks(database) -> int:
    """Return expired leases to the queue or terminally fail exhausted tasks."""
    now = datetime.utcnow()
    collection = database[TASK_COLLECTION]
    exhausted = await collection.update_many(
        {
            "status": "running",
            "lease_expires_at": {"$lte": now},
            "$expr": {"$gte": ["$attempts", "$max_attempts"]},
        },
        {"$set": {
            "status": "failed",
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error": "Worker lease expired after maximum attempts.",
            "updated_at": now,
        }},
    )
    retryable = await collection.update_many(
        {
            "status": "running",
            "lease_expires_at": {"$lte": now},
            "$expr": {"$lt": ["$attempts", "$max_attempts"]},
        },
        {"$set": {
            "status": "queued",
            "lease_owner": None,
            "lease_expires_at": None,
            "last_error": "Worker lease expired; task requeued.",
            "updated_at": now,
        }},
    )
    return exhausted.modified_count + retryable.modified_count


async def recover_prepared_output_dispatches(database) -> dict:
    """Finish or reject the tiny prepare/activate crash window safely.

    The core writes a durable ``prepared`` marker only after every expected
    sibling task exists in the held state. On restart, a complete task set is
    released; an incomplete set has durable ownership removed so ordinary
    orphan recovery can mark the job recoverable instead of leaving it stuck.
    """
    jobs = database["jobs"]
    tasks = database[TASK_COLLECTION]
    activated_jobs = 0
    rejected_jobs = 0
    cursor = jobs.find({
        "output_execution_mode": "durable_workers",
        "output_dispatch_state": "prepared",
    })
    async for job in cursor:
        job_id = job.get("job_id")
        version = job.get("output_manifest_version")
        expected = int(job.get("output_expected_tasks") or 0)
        identity = {"job_id": job_id, "manifest_version": version}
        task_count = await tasks.count_documents(identity)
        if expected > 0 and task_count == expected:
            await tasks.update_many(
                {**identity, "status": "held"},
                {"$set": {"status": "queued", "updated_at": datetime.utcnow()}},
            )
            await jobs.update_one(
                {"job_id": job_id, "output_dispatch_state": "prepared"},
                {"$set": {
                    "output_dispatch_state": "active",
                    "updated_at": datetime.utcnow(),
                }},
            )
            activated_jobs += 1
            continue

        await tasks.update_many(
            {**identity, "status": "held"},
            {"$set": {
                "status": "cancelled",
                "last_error": "Incomplete output dispatch recovered after API restart.",
                "updated_at": datetime.utcnow(),
            }},
        )
        await jobs.update_one(
            {"job_id": job_id, "output_dispatch_state": "prepared"},
            {"$unset": {
                "output_execution_mode": "",
                "output_dispatch_state": "",
                "output_manifest_version": "",
                "output_expected_tasks": "",
            }},
        )
        rejected_jobs += 1
    return {"activated": activated_jobs, "rejected": rejected_jobs}


async def reconcile_job_output_status(database, job_id: str) -> Optional[str]:
    """Derive legacy aggregate status after a component state is persisted."""
    jobs = database["jobs"]
    job = await jobs.find_one({"job_id": job_id})
    if not job:
        return None
    video = (job.get("video_component") or {}).get("status", "queued")
    text = (job.get("text_component") or {}).get("status", "queued")
    requested = [text]
    if job.get("generate_video"):
        requested.append(video)
    terminal_values = {"ready", "failed", "cancelled", "not_requested"}
    terminal = all(value in terminal_values for value in requested)
    ready = sum(value == "ready" for value in requested)
    now = datetime.utcnow()

    if terminal:
        if ready == len(requested):
            status, message = "completed", "Your summary is ready!"
        elif ready:
            status, message = "partial_success", "One output is ready; another output was unavailable."
        else:
            status, message = "error", "Video and written summary outputs were unavailable."
        payload = {
            "status": status,
            "stage_message": message,
            "progress_percent": 100,
            "completed_at": now,
            "updated_at": now,
        }
    elif video == "ready":
        status = "video_ready"
        payload = {
            "status": status,
            "stage_message": "Highlight video ready — generating AI summary...",
            "progress_percent": 82,
            "updated_at": now,
        }
    elif text == "ready":
        status = "generating_video"
        payload = {
            "status": status,
            "stage_message": "Written summary ready — generating highlight video...",
            "progress_percent": 90,
            "updated_at": now,
        }
    else:
        return job.get("status")
    await jobs.update_one({"job_id": job_id}, {"$set": payload})
    return status


async def finish_output_task(
    database,
    *,
    task_id: str,
    worker_id: str,
    succeeded: bool,
    error: Optional[str] = None,
) -> bool:
    now = datetime.utcnow()
    task = await database[TASK_COLLECTION].find_one({"task_id": task_id})
    if not task or task.get("lease_owner") != worker_id or task.get("status") != "running":
        return False
    retry = not succeeded and int(task.get("attempts", 0)) < int(task.get("max_attempts", 3))
    status = "completed" if succeeded else ("queued" if retry else "failed")
    result = await database[TASK_COLLECTION].update_one(
        {"task_id": task_id, "status": "running", "lease_owner": worker_id},
        {"$set": {
            "status": status,
            "last_error": error,
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": now,
            **({"completed_at": now} if succeeded else {}),
        }},
    )
    return result.modified_count == 1
