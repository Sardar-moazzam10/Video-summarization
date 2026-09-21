"""One reproducible real-media baseline run using existing local source caches.

Run from the repository root:
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 venv/bin/python -m evaluation.validate_multi_video
No generated captions, fake vectors, source downloads, or database writes.
"""
import asyncio
import json
from pathlib import Path
import subprocess
from time import perf_counter

from backend.api.merge import run_semantic_selection
from backend.models.job import MergeJob
from backend.services.fusion_engine import get_sentence_transformer
from backend.services.video_service import VideoService


async def main():
    report_path = Path("evaluation/multi_video_validation.json")
    report = {"status": "started", "scope": "cached real sources, first 600 seconds each; selection and FFmpeg, not HTTP/auth or fresh ASR",
              "model": "BAAI/bge-base-en-v1.5", "stage_timings_seconds": {}}
    times = report["stage_timings_seconds"]
    try:
        started = perf_counter()
        ids = ["7eh4d6sabA0", "nm1TxQj9IsQ"]
        paths = {vid: str(Path("audio_cache/video_cache") / vid / "video.mp4") for vid in ids}
        for path in paths.values():
            if not Path(path).is_file():
                raise FileNotFoundError(path)
        times["download_cache"] = perf_counter() - started
        started = perf_counter()
        transcripts = json.loads(Path("evaluation/transcripts.json").read_text())
        raw = {vid: [s for s in transcripts[vid] if s["start"] + s.get("duration", 0) <= 600] for vid in ids}
        times["transcription"] = perf_counter() - started
        report["transcription_mode"] = "existing real caption cache; timing is cache read, not ASR"
        report["input_videos"] = [{"video_id": vid, "url": f"https://www.youtube.com/watch?v={vid}",
                                    "source_path": paths[vid], "caption_entries": len(raw[vid]),
                                    "window_seconds": [0, 600]} for vid in ids]
        started = perf_counter()
        get_sentence_transformer()
        times["model_load"] = perf_counter() - started
        job = MergeJob(job_id="phase2-real-validation", video_ids=ids,
                       target_duration_minutes=5, highlight_duration_seconds=300,
                       generate_video=True, generate_audio=False)
        selected = await run_semantic_selection(job, raw, "")
        if not selected:
            raise RuntimeError("No usable selection")
        manifest = selected["highlights"]
        times.update(selected["metrics"]["stage_timings_seconds"])
        report.update({"source_segments": selected["metrics"]["candidate_count"],
                       "selected_clips": len(manifest),
                       "clips_per_source": {vid: sum(c["video_id"] == vid for c in manifest) for vid in ids},
                       "concepts_covered": sorted({c for clip in manifest for c in clip["covered_concepts"]}),
                       "duplicates_rejected": selected["metrics"]["duplicates_rejected"],
                       "requested_seconds": 300,
                       "selected_seconds": sum(c["end_time"] - c["start_time"] for c in manifest),
                       "incomplete_thought_clips": selected["metrics"]["incomplete_thought_clips"],
                       "thought_check": "segmenter completeness flags only; human audiovisual review still required",
                       "manifest": manifest, "metrics": selected["metrics"]})
        # Persist selection evidence even if rendering fails.
        report_path.write_text(json.dumps(report, indent=2))
        started = perf_counter()
        video = await VideoService().generate_highlight_reel(job.job_id, manifest, paths)
        times["rendering"] = perf_counter() - started
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=noprint_wrappers=1:nokey=1", video],
                               capture_output=True, text=True, check=True, timeout=30)
        report["rendered_seconds"] = float(probe.stdout.strip())
        report["rendered_path"] = video
        report["duration_difference_seconds"] = report["rendered_seconds"] - report["selected_seconds"]
        report["status"] = "passed" if abs(report["duration_difference_seconds"]) < 1 else "duration_mismatch"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(json.dumps(report, indent=2))
        print(f"Validation report: {report_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
