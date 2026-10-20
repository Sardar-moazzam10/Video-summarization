"""Dedicated manifest-consuming text worker.

Run with: ``python -m backend.workers.text_worker``.
"""

import asyncio
from datetime import datetime
import os
import socket

from ..core.database import get_database
from ..models.output_contracts import EvidenceManifest
from ..services.output_task_queue import (
    claim_output_task,
    finish_output_task,
    maintain_output_task_lease,
    reconcile_job_output_status,
)
from ..services.text_output_service import generate_structured_text


WORKER_ID = f"text:{socket.gethostname()}:{os.getpid()}"


async def process_one(database) -> bool:
    lease_seconds = 300
    task = await claim_output_task(
        database, output_type="text", worker_id=WORKER_ID, lease_seconds=lease_seconds,
    )
    if not task:
        return False
    task_id = task["task_id"]
    lease_stop = asyncio.Event()
    lease_task = asyncio.create_task(maintain_output_task_lease(
        database,
        task_id=task_id,
        worker_id=WORKER_ID,
        stop_event=lease_stop,
        lease_seconds=lease_seconds,
    ))
    try:
        jobs = database["jobs"]
        job = await jobs.find_one({"job_id": task["job_id"]})
        if not job or not job.get("evidence_manifest"):
            raise ValueError("job has no published evidence manifest")
        manifest = EvidenceManifest.model_validate(job["evidence_manifest"])
        if manifest.manifest_version != task["manifest_version"]:
            raise ValueError("task manifest version no longer matches job")
        result = await asyncio.to_thread(generate_structured_text, manifest)
        if lease_task.done() and lease_task.result() is False:
            raise RuntimeError("text worker lost task lease before publication")
        if not result.validation.get("valid"):
            raise ValueError(f"text output validation failed: {result.validation['errors']}")
        now = datetime.utcnow()
        summary_text = "\n\n".join(item.text for item in result.summary)
        rich_output = {
            "summary": summary_text,
            "tldr": result.tldr.text,
            "key_takeaways": [item.text for item in result.key_takeaways],
            "chapters": [],
            "best_quotes": [],
            "who_should_watch": "",
            "who_can_skip": "",
            "action_steps": [],
            "style_applied": manifest.intent.style,
        }
        published = await jobs.update_one(
            {"job_id": task["job_id"], "evidence_manifest.manifest_version": task["manifest_version"]},
            {"$set": {
                "structured_text_output": result.model_dump(),
                "summary_text": summary_text,
                "rich_output": rich_output,
                "text_component": {
                    "status": "ready", "stage": "ready", "progress_percent": 100,
                    "attempts": task["attempts"], "error": None, "updated_at": now,
                },
            }},
        )
        if published.modified_count != 1:
            raise RuntimeError("text output was not published because the manifest changed")
        await reconcile_job_output_status(database, task["job_id"])
        await finish_output_task(
            database, task_id=task_id, worker_id=WORKER_ID, succeeded=True,
        )
    except Exception as exc:
        if lease_task.done() and lease_task.result() is False:
            # Another worker owns the task now. A stale worker must never
            # publish failure state or alter the new owner's retry lifecycle.
            return True
        await finish_output_task(
            database, task_id=task_id, worker_id=WORKER_ID,
            succeeded=False, error=str(exc),
        )
        current_task = await database["output_tasks"].find_one({"task_id": task_id})
        task_status = (current_task or {}).get("status")
        component_status = "queued" if task_status == "queued" else "failed"
        await database["jobs"].update_one(
            {"job_id": task["job_id"]},
            {"$set": {"text_component": {
                "status": component_status,
                "stage": "retry_queued" if component_status == "queued" else "failed",
                "progress_percent": 0 if component_status == "queued" else 100,
                "attempts": task.get("attempts", 1),
                "error": str(exc),
                "updated_at": datetime.utcnow(),
            }}},
        )
        await reconcile_job_output_status(database, task["job_id"])
    finally:
        lease_stop.set()
        await lease_task
    return True


async def run_forever(poll_seconds: float = 1.0):
    database = await get_database()
    while True:
        worked = await process_one(database)
        if not worked:
            await asyncio.sleep(poll_seconds)


if __name__ == "__main__":
    asyncio.run(run_forever())
