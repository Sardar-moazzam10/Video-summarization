"""
Unit tests for Storage Hygiene Service.
Verifies temp scratch cleanup, download directory cleanup,
highlights LRU eviction, and companion audio deletion.
"""

import os
import time
import tempfile
import pytest
from pathlib import Path
from backend.services.storage_hygiene import (
    cleanup_temp_scratch,
    cleanup_download_scratch,
    prune_highlights_cache,
    run_storage_hygiene,
)


def test_cleanup_temp_scratch_removes_old_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))

    old_dir = tmp_path / "highlight_test_job_old"
    old_dir.mkdir()
    (old_dir / "clip_0.mp4").write_bytes(b"x" * 1024)

    new_dir = tmp_path / "highlight_test_job_new"
    new_dir.mkdir()
    (new_dir / "clip_0.mp4").write_bytes(b"x" * 1024)

    other_dir = tmp_path / "other_scratch_dir"
    other_dir.mkdir()

    # Artificially age old_dir to 2 hours ago
    two_hours_ago = time.time() - 7200
    os.utime(str(old_dir), (two_hours_ago, two_hours_ago))

    result = cleanup_temp_scratch(max_age_minutes=30)
    assert result["cleaned_dirs"] == 1
    assert not old_dir.exists()
    assert new_dir.exists()
    assert other_dir.exists()


def test_cleanup_download_scratch_removes_stale_downloads(tmp_path):
    base_dir = tmp_path / "video_downloads"
    base_dir.mkdir()

    stale_job = base_dir / "stale_job_123"
    stale_job.mkdir()
    (stale_job / "source.mp4").write_bytes(b"y" * 2048)

    active_job = base_dir / "active_job_456"
    active_job.mkdir()
    (active_job / "source.mp4").write_bytes(b"y" * 2048)

    one_hour_ago = time.time() - 3600
    os.utime(str(stale_job), (one_hour_ago, one_hour_ago))

    result = cleanup_download_scratch(max_age_minutes=30, base_dir=base_dir)
    assert result["cleaned_dirs"] == 1
    assert not stale_job.exists()
    assert active_job.exists()


def test_prune_highlights_cache_enforces_lru_and_companion_audio(tmp_path, monkeypatch):
    cache_root = tmp_path / "audio_cache"
    highlights_dir = cache_root / "highlights"
    highlights_dir.mkdir(parents=True)

    # File 1: Oldest file (1 MB)
    h1 = highlights_dir / "highlight_job1.mp4"
    h1.write_bytes(b"1" * (1024 * 1024))
    t1 = time.time() - 1000
    os.utime(str(h1), (t1, t1))

    # Companion audio for Job 1
    a1 = cache_root / "summary_job1.mp3"
    a1.write_bytes(b"audio" * 100)

    # File 2: Newer file (1 MB)
    h2 = highlights_dir / "highlight_job2.mp4"
    h2.write_bytes(b"2" * (1024 * 1024))
    t2 = time.time() - 500
    os.utime(str(h2), (t2, t2))

    # File 3: Newest file (1 MB)
    h3 = highlights_dir / "highlight_job3.mp4"
    h3.write_bytes(b"3" * (1024 * 1024))
    t3 = time.time()
    os.utime(str(h3), (t3, t3))

    # Current total size = 3 MB
    # Prune with max_size_gb equivalent to 1.5 MB (0.00146484 GB)
    # This should evict h1 (and delete a1), leaving h2 and h3 (2 MB <= next bound or evicted until under limit)
    # If limit is 1.5 MB, evicting h1 leaves 2 MB (still > 1.5 MB), so h2 is also evicted, leaving only h3.
    target_limit_gb = (1.5 * 1024 * 1024) / (1024 * 1024 * 1024)
    result = prune_highlights_cache(max_size_gb=target_limit_gb, max_age_days=30, highlights_dir=highlights_dir)

    assert result["removed_count"] == 2
    assert not h1.exists()
    assert not a1.exists(), "Companion audio should have been removed when highlight was pruned"
    assert not h2.exists()
    assert h3.exists(), "Newest highlight must be preserved"
    assert result["remaining_count"] == 1


def test_run_storage_hygiene_executes_safely():
    report = run_storage_hygiene()
    assert "temp_scratch" in report
    assert "download_scratch" in report
    assert "highlights" in report
    assert "video_cache" in report

