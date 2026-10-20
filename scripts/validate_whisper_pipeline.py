"""Exercise a cached real Whisper transcript through the normal merge pipeline."""

import asyncio
import contextlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.api.merge import _active_jobs, get_jobs_collection, process_merge_job
from backend.models.job import MergeJob
from backend.services.media_probe import get_video_duration_seconds


async def main(video_id: str) -> None:
    duration = get_video_duration_seconds(video_id)
    if not duration:
        raise RuntimeError(f"Could not resolve duration for {video_id}")

    job = MergeJob(
        user_id="whisper-real-validation",
        video_ids=[video_id],
        requested_video_ids=[video_id],
        used_video_ids=[video_id],
        target_duration_minutes=5,
        highlight_duration_seconds=300,
        generate_audio=False,
        generate_video=False,
        source_durations={video_id: duration},
        style="educational",
    )
    collection = await get_jobs_collection()
    await collection.insert_one(job.model_dump())
    _active_jobs[job.job_id] = job
    task = asyncio.create_task(process_merge_job(job.job_id))
    stored = {}
    while True:
        await asyncio.sleep(1)
        stored = await collection.find_one({"job_id": job.job_id}) or {}
        if stored.get("status") in {"completed", "partial_success", "error", "cancelled"}:
            break
        if task.done():
            await task
            break
    # process_merge_job intentionally retains its in-memory job for five minutes
    # after persistence. Validation needs the persisted result, not that delay.
    if not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    timings = stored.get("stage_timings_seconds") or {}
    report = {
        "job_id": job.job_id,
        "video_id": video_id,
        "status": stored.get("status"),
        "transcript_method": (stored.get("transcript_preflight") or {}).get(video_id, {}).get("method"),
        "semantic_pipeline_entered": float(timings.get("fusion_analysis", 0) or 0) > 0,
        "selection_mode": stored.get("selection_mode"),
        "concepts": len(stored.get("concepts") or []),
        "highlight_segments_generated": len(stored.get("highlight_segments") or []),
        "written_summary_generated": bool((stored.get("summary_text") or "").strip()),
        "summary_words": len((stored.get("summary_text") or "").split()),
        "video_rendered": bool(stored.get("video_path")),
        "summary_unavailable": stored.get("summary_unavailable", False),
        "failure": stored.get("error"),
    }
    print("PIPELINE_VALIDATION_JSON=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: validate_whisper_pipeline.py VIDEO_ID")
    asyncio.run(main(sys.argv[1]))
