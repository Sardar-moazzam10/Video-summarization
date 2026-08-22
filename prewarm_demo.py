r"""
Demo Warm-Up Script — make a presentation run with zero network latency.

Run this the night before a demo. It front-loads everything the pipeline would
otherwise fetch live, so during the presentation there is no download, no
transcript API call, and no cold model load:

  1. TRANSCRIPTS  — fetched via the 3-tier service and cached in MongoDB.
  2. VIDEOS       — downloaded into the local video cache (audio_cache/video_cache).
  3. PINNED       — each cached video is marked pinned, so cleanup_old_cache()
                    will never evict it, by age OR by size. This is the part a
                    "just re-download it" approach cannot guarantee.
  4. MODELS       — optionally pre-loaded so the first real request is not
                    paying for BART / Sentence-BERT initialisation.

Nothing here touches the merge pipeline or the evaluation code. It only fills
caches that the pipeline already reads from, so it is safe to run at any time.

USAGE
-----
    # Warm up the videos you will demo with
    ./venv/bin/python prewarm_demo.py VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3

    # Full YouTube URLs work too
    ./venv/bin/python prewarm_demo.py "https://youtu.be/dQw4w9WgXcQ"

    # Also pre-load the ML models (adds ~30-60s, makes the first run faster)
    ./venv/bin/python prewarm_demo.py VIDEO_ID --preload-models

    # Check what is currently warm and pinned
    ./venv/bin/python prewarm_demo.py --status

    # Release videos after the demo so normal LRU cleanup resumes
    ./venv/bin/python prewarm_demo.py VIDEO_ID --unpin

    # Warm the transcript only (skip the video download)
    ./venv/bin/python prewarm_demo.py VIDEO_ID --no-video

VERIFY BEFORE YOU PRESENT
-------------------------
Run with --status and confirm every demo video shows [cached] and [pinned].
"""

import argparse
import asyncio
import os
import sys
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ──────────────────────────────────────────────────────────────────────────────
# Output helpers
# ──────────────────────────────────────────────────────────────────────────────

def _hr(title: str = "") -> None:
    line = "─" * 64
    print(f"\n{line}")
    if title:
        print(f"  {title}")
        print(line)


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


# ──────────────────────────────────────────────────────────────────────────────
# Step 1 — transcripts
# ──────────────────────────────────────────────────────────────────────────────

async def warm_transcript(video_id: str) -> bool:
    """Fetch + cache the transcript in MongoDB. Returns True on success."""
    from backend.services.transcript_service import get_transcript_service

    try:
        svc = await get_transcript_service()
        result = await svc.get_transcript(video_id)
    except Exception as e:
        _fail(f"transcript {video_id}: {e}")
        return False

    if not result or not result.get("transcript"):
        _fail(f"transcript {video_id}: no transcript available")
        return False

    segments = result["transcript"]
    words = sum(len(s.get("text", "").split()) for s in segments)
    origin = "already cached" if result.get("cached") else f"fetched via {result.get('source')}"
    _ok(f"transcript {video_id}: {len(segments)} segments, {words} words ({origin})")
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Step 2 + 3 — video download and pin
# ──────────────────────────────────────────────────────────────────────────────

def warm_and_pin_video(video_id: str, pin: bool = True) -> bool:
    """Download into the video cache (if needed) and pin it against eviction."""
    try:
        from video_cache_manager import get_video_cache_manager
        mgr = get_video_cache_manager()
    except Exception as e:
        _fail(f"video cache manager unavailable: {e}")
        return False

    try:
        cached = mgr.get_cached_video(video_id)
        if cached:
            _ok(f"video {video_id}: already cached ({_mb(os.path.getsize(cached))})")
        else:
            print(f"  ...    downloading {video_id} (this is the slow part — "
                  f"doing it now so the demo does not)")
            path = mgr.download_and_cache_video(video_id)
            if not path or not os.path.exists(path):
                _fail(f"video {video_id}: download produced no file")
                return False
            _ok(f"video {video_id}: downloaded ({_mb(os.path.getsize(path))})")
    except Exception as e:
        _fail(f"video {video_id}: {e}")
        return False

    if pin:
        if mgr.set_pinned(video_id, True):
            _ok(f"video {video_id}: PINNED — protected from age and size eviction")
        else:
            _warn(f"video {video_id}: could not pin (not found in cache)")
            return False

    return True


def unpin_video(video_id: str) -> None:
    from video_cache_manager import get_video_cache_manager
    mgr = get_video_cache_manager()
    if mgr.set_pinned(video_id, False):
        _ok(f"video {video_id}: unpinned — normal LRU cleanup applies again")
    else:
        _warn(f"video {video_id}: not in cache, nothing to unpin")


# ──────────────────────────────────────────────────────────────────────────────
# Step 4 — models
# ──────────────────────────────────────────────────────────────────────────────

def preload_models() -> None:
    """Load BART + Sentence-BERT so the first real request skips cold start."""
    try:
        from backend.services.summarization_service import _get_pipeline
        _get_pipeline()
        _ok("BART summarization model loaded")
    except Exception as e:
        _warn(f"BART preload failed: {e}")

    try:
        from backend.services.fusion_engine import get_sentence_transformer
        get_sentence_transformer()
        _ok("Sentence-BERT embedding model loaded")
    except Exception as e:
        _warn(f"Sentence-BERT preload failed: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Status
# ──────────────────────────────────────────────────────────────────────────────

async def show_status(video_ids: List[str]) -> None:
    """Report cache + pin + transcript state. Run this before presenting."""
    from video_cache_manager import get_video_cache_manager
    mgr = get_video_cache_manager()

    _hr("CACHE STATUS")
    try:
        stats = mgr.get_cache_stats()
        print(f"  total cached: {stats.get('video_count', '?')} videos, "
              f"{stats.get('total_size_mb', 0):.1f} MB "
              f"(limit {stats.get('max_size_gb', '?')} GB / "
              f"{stats.get('max_age_days', '?')} days)")
    except Exception as e:
        _warn(f"could not read cache stats: {e}")

    pinned = mgr.list_pinned()
    print(f"  pinned:       {len(pinned)} video(s) {pinned if pinned else ''}")

    # Which transcripts are in MongoDB?
    cached_transcripts = set()
    try:
        from backend.core.database import get_database
        db = await get_database()
        async for doc in db["transcripts"].find({}, {"video_id": 1}):
            cached_transcripts.add(doc.get("video_id"))
    except Exception as e:
        _warn(f"could not read transcript cache: {e}")

    if video_ids:
        _hr("DEMO VIDEOS")
        all_ready = True
        for vid in video_ids:
            has_video = bool(mgr.get_cached_video(vid))
            is_pinned = mgr.is_pinned(vid)
            has_tx = vid in cached_transcripts
            ready = has_video and is_pinned and has_tx
            all_ready = all_ready and ready
            marks = (f"{'[cached]' if has_video else '[NO VIDEO]':<11}"
                     f"{'[pinned]' if is_pinned else '[NOT PINNED]':<14}"
                     f"{'[transcript]' if has_tx else '[NO TRANSCRIPT]'}")
            print(f"  {'OK ' if ready else '!! '} {vid:<16} {marks}")

        print()
        if all_ready:
            print("  ALL DEMO VIDEOS ARE WARM AND PINNED — safe to present.")
        else:
            print("  NOT READY. Re-run without --status to warm the missing items.")


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

async def _main() -> int:
    p = argparse.ArgumentParser(
        description="Pre-download and pin demo videos so a live run has zero network latency.",
    )
    p.add_argument("video_ids", nargs="*", help="YouTube video IDs or URLs")
    p.add_argument("--status", action="store_true", help="Show cache/pin state and exit")
    p.add_argument("--unpin", action="store_true", help="Unpin the given videos")
    p.add_argument("--no-video", action="store_true", help="Warm transcripts only")
    p.add_argument("--no-pin", action="store_true", help="Download but do not pin")
    p.add_argument("--preload-models", action="store_true", help="Also load BART + SBERT")
    args = p.parse_args()

    # Accept full URLs as well as bare IDs
    from backend.services.transcript_service import extract_video_id
    video_ids = [extract_video_id(v) for v in args.video_ids]

    if args.status:
        await show_status(video_ids)
        return 0

    if not video_ids:
        p.error("give at least one video ID (or use --status)")

    if args.unpin:
        _hr("UNPINNING")
        for vid in video_ids:
            unpin_video(vid)
        return 0

    _hr(f"WARMING {len(video_ids)} DEMO VIDEO(S)")
    print("  Doing the slow work now so the presentation does not have to.\n")

    failures = []
    for i, vid in enumerate(video_ids, 1):
        print(f"  [{i}/{len(video_ids)}] {vid}")
        tx_ok = await warm_transcript(vid)
        vid_ok = True
        if not args.no_video:
            vid_ok = warm_and_pin_video(vid, pin=not args.no_pin)
        if not (tx_ok and vid_ok):
            failures.append(vid)
        print()

    if args.preload_models:
        _hr("PRELOADING MODELS")
        preload_models()

    await show_status(video_ids)

    if failures:
        _hr("RESULT")
        _fail(f"{len(failures)} video(s) failed: {', '.join(failures)}")
        print("  Fix these before the demo, or choose different videos.")
        return 1

    _hr("RESULT")
    _ok("All demo videos warmed and pinned.")
    print("  Re-run with --status any time to re-check before presenting.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
