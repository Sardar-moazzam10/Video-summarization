"""Real-video validation for canonical-English Whisper recovery."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import time

from backend.services.media_probe import get_video_duration_seconds
from backend.services.transcript_service import get_transcript_service, _whisper_model_name


async def validate(video_id: str) -> dict:
    service = await get_transcript_service()
    before = await service.transcripts.find_one({"video_id": video_id})
    started = time.perf_counter()
    result = await service.get_transcript(video_id, allow_whisper=True)
    elapsed = time.perf_counter() - started
    rows = (result or {}).get("transcript") or []
    after = await service.transcripts.find_one({"video_id": video_id})
    duration = get_video_duration_seconds(video_id)

    first = rows[0] if rows else {}
    last = rows[-1] if rows else {}
    timestamp_end = last.get("end")
    if timestamp_end is None and last:
        timestamp_end = float(last.get("start", 0)) + float(last.get("duration", 0))

    return {
        "video_id": video_id,
        "duration_seconds": duration,
        "detected_source_language": first.get("original_language") or "unknown",
        "raw_captions_available": bool(before and before.get("transcript")),
        "youtube_english_translation_available": False,
        "whisper_invoked": (result or {}).get("source") == "whisper_translate" and not (result or {}).get("cached"),
        "whisper_model": _whisper_model_name(),
        "number_of_audio_chunks": (
            None if duration is None else max(1, int((duration - 1) // 899) + 1)
        ),
        "wall_clock_seconds": round(elapsed, 2),
        "final_language": service._detect_transcript_language(rows) if rows else None,
        "final_segments": len(rows),
        "timestamp_start": first.get("start") if rows else None,
        "timestamp_end": timestamp_end,
        "cache_reused": (result or {}).get("cached"),
        "cache_written": (after or {}).get("source") == "whisper_translate",
        "cache_identity": (after or {}).get("whisper_cache_identity"),
        "transcript_source": (result or {}).get("source"),
        "semantic_pipeline_eligible": bool(rows) and service._detect_transcript_language(rows) == "en",
        "failure": None if rows else "No canonical transcript was generated",
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video_ids", nargs="+")
    args = parser.parse_args()
    for video_id in args.video_ids:
        try:
            report = await validate(video_id)
        except Exception as exc:
            report = {
                "video_id": video_id,
                "failure": f"{type(exc).__name__}: {exc}",
            }
        print("REAL_VALIDATION_JSON=" + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
