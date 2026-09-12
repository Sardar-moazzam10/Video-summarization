"""
Tests for VideoService._trim_segments_bounded — the bounded-concurrency fix
for the highlight-reel clip trim/normalize stage.

Real measured problem: this loop ran strictly sequentially, one ffmpeg
subprocess at a time. On a real 33-clip job it took 155.8s — the single
largest contributor to total job latency (out of ~384s end to end). A real
benchmark (1/2/4/6/8 concurrent workers, same 33 real clips) showed no
correctness regressions (clip duration, A/V sync, final duration, black
frames all identical across every worker count) and picked 6 as the best
speed/memory balance on this machine — see MAX_CONCURRENT_CLIP_ENCODES's
comment in video_service.py.

These tests prove the concurrency bound and ordering guarantees the fix
depends on, without touching a real ffmpeg process.
"""

import asyncio

import pytest

from backend.services.video_service import VideoService, MAX_CONCURRENT_CLIP_ENCODES


def _make_segments(n: int):
    return [{"video_id": "vid", "start_time": float(i * 10), "end_time": float(i * 10 + 8)} for i in range(n)]


class TestBoundedConcurrency:
    @pytest.mark.asyncio
    async def test_never_exceeds_the_configured_worker_limit(self, monkeypatch):
        """
        Directly measures the high-water mark of concurrently in-flight
        trim calls under real asyncio scheduling — not just trusting the
        Semaphore exists, but proving it's actually bounding execution.
        """
        active = 0
        max_active = 0
        lock = asyncio.Lock()

        async def fake_trim(seg, video_paths, work_dir, idx):
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.02)  # widen the window so overlaps are reliably observed
            async with lock:
                active -= 1
            return f"clip_{idx:04d}.mp4"

        svc = VideoService()
        monkeypatch.setattr(svc, "_trim_and_normalize_segment", fake_trim)

        segments = _make_segments(20)  # well over MAX_CONCURRENT_CLIP_ENCODES
        await svc._trim_segments_bounded(segments, {"vid": "/fake/path.mp4"}, "/fake/workdir")

        assert max_active <= MAX_CONCURRENT_CLIP_ENCODES
        assert max_active > 1, "test is meaningless if nothing ever actually overlapped"

    @pytest.mark.asyncio
    async def test_output_order_matches_input_order_regardless_of_completion_order(self, monkeypatch):
        """
        Concat depends on clip order matching segment order. Deliberately
        makes EARLIER segments finish LAST (reversed delay) to prove the
        result list isn't just "whatever asyncio.gather happened to return
        in completion order" — gather preserves call order by construction,
        but this locks that guarantee in against a future refactor.
        """
        n = 10

        async def fake_trim(seg, video_paths, work_dir, idx):
            await asyncio.sleep(0.01 * (n - idx))  # segment 0 takes longest, finishes last
            return f"clip_{idx:04d}.mp4"

        svc = VideoService()
        monkeypatch.setattr(svc, "_trim_and_normalize_segment", fake_trim)

        segments = _make_segments(n)
        result = await svc._trim_segments_bounded(segments, {"vid": "/fake/path.mp4"}, "/fake/workdir")

        assert result == [f"clip_{i:04d}.mp4" for i in range(n)]

    @pytest.mark.asyncio
    async def test_failed_clips_are_dropped_without_disturbing_the_rest(self, monkeypatch):
        """A None from _trim_and_normalize_segment (existing failure contract) must be filtered, not crash the batch."""

        async def fake_trim(seg, video_paths, work_dir, idx):
            if idx in (2, 5):
                return None  # simulates a timeout/ffmpeg failure for this clip
            return f"clip_{idx:04d}.mp4"

        svc = VideoService()
        monkeypatch.setattr(svc, "_trim_and_normalize_segment", fake_trim)

        segments = _make_segments(8)
        result = await svc._trim_segments_bounded(segments, {"vid": "/fake/path.mp4"}, "/fake/workdir")

        assert result == [f"clip_{i:04d}.mp4" for i in range(8) if i not in (2, 5)]
        assert len(result) == 6

    @pytest.mark.asyncio
    async def test_every_segment_is_attempted_exactly_once(self, monkeypatch):
        calls = []

        async def fake_trim(seg, video_paths, work_dir, idx):
            calls.append(idx)
            return f"clip_{idx:04d}.mp4"

        svc = VideoService()
        monkeypatch.setattr(svc, "_trim_and_normalize_segment", fake_trim)

        segments = _make_segments(15)
        await svc._trim_segments_bounded(segments, {"vid": "/fake/path.mp4"}, "/fake/workdir")

        assert sorted(calls) == list(range(15))

    @pytest.mark.asyncio
    async def test_all_clips_failing_returns_empty_list_not_an_error(self, monkeypatch):
        async def fake_trim(seg, video_paths, work_dir, idx):
            return None

        svc = VideoService()
        monkeypatch.setattr(svc, "_trim_and_normalize_segment", fake_trim)

        segments = _make_segments(5)
        result = await svc._trim_segments_bounded(segments, {"vid": "/fake/path.mp4"}, "/fake/workdir")

        assert result == []
