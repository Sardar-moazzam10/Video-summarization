"""
Tests for video_cache_manager download and caching fixes.

Validates:
  1. Cache download command includes --merge-output-format mp4.
  2. Successful MP4 output is accepted by validation.
  3. Invalid container / extension mismatch is rejected.
  4. Cache manager does NOT retry a valid MP4 unnecessarily.
  5. Requested video quality targets 360p (not 1080p).

These are the exact regressions that caused 3× wasted full-resolution
downloads on every cache-enabled job:

  - yt-dlp merged mp4 video + webm audio → MKV container
  - validation expected video.temp.mp4 → file not found
  - retry loop downloaded 1080p 3 times (50–150s each)
  - fallback to video_service succeeded at 360p because it had
    both --merge-output-format mp4 AND height<=360

Everything here is mocked — no real YouTube API, yt-dlp, or FFprobe calls.
"""

import os
import json
import subprocess
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cache_manager():
    """Import and instantiate a fresh VideoCacheManager."""
    # Ensure the module-level guards see cache as enabled
    with patch.dict(os.environ, {"VIDEO_CACHE_ENABLED": "1"}):
        import importlib
        import video_cache_manager as vcm
        importlib.reload(vcm)
        return vcm.VideoCacheManager()


def _make_valid_mp4(path: str, size: int = 1024):
    """Create a non-empty file at `path` to simulate a downloaded video."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x00" * size)


# ---------------------------------------------------------------------------
# 1. Cache download requests MP4 output
# ---------------------------------------------------------------------------

class TestCacheDownloadRequestsMP4:
    """The yt-dlp command MUST include --merge-output-format mp4."""

    def test_download_with_retry_includes_merge_output_format(self):
        """
        The cache manager's _download_with_retry must pass
        --merge-output-format mp4 to yt-dlp, otherwise a webm audio
        track causes yt-dlp to emit MKV and the validation on
        video.temp.mp4 silently fails.
        """
        mgr = _make_cache_manager()
        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            # Simulate a failed download so we only get one attempt
            raise subprocess.CalledProcessError(1, cmd, stderr="simulated")

        with patch("video_cache_manager.subprocess.run", side_effect=fake_run):
            with patch("video_cache_manager.DOWNLOAD_RETRY_ATTEMPTS", 1):
                result = mgr._download_with_retry("testVid", "/tmp/out.mp4")

        assert len(captured_cmds) == 1, "Expected exactly 1 attempt"
        cmd = captured_cmds[0]
        assert "--merge-output-format" in cmd, (
            "yt-dlp command is missing --merge-output-format"
        )
        idx = cmd.index("--merge-output-format")
        assert cmd[idx + 1] == "mp4", (
            f"Expected mp4 after --merge-output-format, got {cmd[idx + 1]!r}"
        )

    def test_download_to_work_dir_includes_merge_output_format(self):
        """
        The _download_to_work_dir fallback must also include
        --merge-output-format mp4 for consistency.
        """
        mgr = _make_cache_manager()
        captured_cmds = []

        with tempfile.TemporaryDirectory() as work_dir:
            # Create a fake downloaded file so the method succeeds
            fake_file = os.path.join(work_dir, "testVid.mp4")
            _make_valid_mp4(fake_file)

            def fake_run(cmd, **kwargs):
                captured_cmds.append(cmd)
                return MagicMock(returncode=0)

            with patch("video_cache_manager.subprocess.run", side_effect=fake_run):
                mgr._download_to_work_dir("testVid", work_dir)

        assert len(captured_cmds) == 1
        cmd = captured_cmds[0]
        assert "--merge-output-format" in cmd, (
            "_download_to_work_dir is missing --merge-output-format mp4"
        )
        idx = cmd.index("--merge-output-format")
        assert cmd[idx + 1] == "mp4"


# ---------------------------------------------------------------------------
# 2. Successful MP4 output is accepted by validation
# ---------------------------------------------------------------------------

class TestMP4ValidationAccepts:
    """A valid MP4 file on disk must be accepted by _validate_cached_video."""

    def test_valid_mp4_accepted(self):
        """
        When a non-empty file exists and ffprobe reports a video stream,
        _validate_cached_video must return True.
        """
        mgr = _make_cache_manager()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            _make_valid_mp4(video_path, size=2048)

            # ffprobe returns "video" for a valid file
            mock_result = MagicMock()
            mock_result.stdout = "video\n"
            mock_result.returncode = 0

            with patch("video_cache_manager.subprocess.run", return_value=mock_result):
                assert mgr._validate_cached_video(video_path) is True


# ---------------------------------------------------------------------------
# 3. Invalid container / extension mismatch is rejected
# ---------------------------------------------------------------------------

class TestInvalidContainerRejected:
    """Files that don't pass ffprobe validation are rejected."""

    def test_missing_file_rejected(self):
        """A nonexistent file must return False."""
        mgr = _make_cache_manager()
        assert mgr._validate_cached_video("/nonexistent/video.mp4") is False

    def test_zero_byte_file_rejected(self):
        """A zero-byte file must return False."""
        mgr = _make_cache_manager()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            with open(video_path, "wb") as f:
                pass  # 0 bytes
            assert mgr._validate_cached_video(video_path) is False

    def test_file_without_video_stream_rejected(self):
        """
        When ffprobe returns output without 'video' (e.g. audio-only,
        corrupt file, or wrong container), validation must return False.
        """
        mgr = _make_cache_manager()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            _make_valid_mp4(video_path)

            mock_result = MagicMock()
            mock_result.stdout = "audio\n"  # no video stream
            mock_result.returncode = 0

            with patch("video_cache_manager.subprocess.run", return_value=mock_result):
                assert mgr._validate_cached_video(video_path) is False

    def test_ffprobe_exception_rejected(self):
        """
        When ffprobe crashes (e.g. corrupt container), the validation
        must return False rather than propagating the exception.
        """
        mgr = _make_cache_manager()

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "video.mp4")
            _make_valid_mp4(video_path)

            with patch(
                "video_cache_manager.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "ffprobe"),
            ):
                assert mgr._validate_cached_video(video_path) is False


# ---------------------------------------------------------------------------
# 4. Cache manager does NOT retry a valid MP4 unnecessarily
# ---------------------------------------------------------------------------

class TestNoDuplicateDownloads:
    """A cached, valid MP4 must be returned directly — no re-download."""

    def test_cache_hit_returns_without_download(self):
        """
        When a valid cached file exists, download_and_cache_video must
        return the cached path without calling _download_with_retry.
        """
        mgr = _make_cache_manager()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up the cache directory structure
            mgr.cache_dir = tmpdir
            video_dir = os.path.join(tmpdir, "cachedVid")
            os.makedirs(video_dir, exist_ok=True)
            video_path = os.path.join(video_dir, "video.mp4")
            _make_valid_mp4(video_path)

            # Write valid metadata
            meta_path = os.path.join(video_dir, "metadata.json")
            with open(meta_path, "w") as f:
                json.dump({
                    "video_id": "cachedVid",
                    "audio_selection_policy": "original-audio-v1",
                    "file_size": 1024,
                    "last_accessed": "2026-01-01T00:00:00",
                    "downloaded_at": "2026-01-01T00:00:00",
                }, f)

            # ffprobe returns valid video
            mock_result = MagicMock()
            mock_result.stdout = "video\n"
            mock_result.returncode = 0

            download_calls = []

            with patch("video_cache_manager.subprocess.run", return_value=mock_result):
                with patch.object(
                    mgr, "_download_with_retry",
                    side_effect=lambda *a, **k: download_calls.append(1) or True,
                ):
                    with patch.dict(os.environ, {"VIDEO_CACHE_ENABLED": "1"}):
                        import video_cache_manager as vcm
                        with patch.object(vcm, "VIDEO_CACHE_ENABLED", True):
                            result = mgr.download_and_cache_video("cachedVid")

            assert result == video_path, (
                f"Expected cached path {video_path}, got {result}"
            )
            assert len(download_calls) == 0, (
                "download was called despite a valid cache hit — "
                "the cache manager is wasting a download"
            )


# ---------------------------------------------------------------------------
# 5. Requested video quality targets low resolution (360p)
# ---------------------------------------------------------------------------

class TestLowResolutionTarget:
    """The format selector must target 360p, not 1080p."""

    def test_format_selector_targets_360p(self):
        """
        The -f argument in _download_with_retry must contain
        height<=360 to restrict quality to approximately 360p.
        """
        mgr = _make_cache_manager()
        captured_cmds = []

        def fake_run(cmd, **kwargs):
            captured_cmds.append(cmd)
            raise subprocess.CalledProcessError(1, cmd, stderr="simulated")

        with patch("video_cache_manager.subprocess.run", side_effect=fake_run):
            with patch("video_cache_manager.DOWNLOAD_RETRY_ATTEMPTS", 1):
                mgr._download_with_retry("testVid", "/tmp/out.mp4")

        cmd = captured_cmds[0]
        # Find the -f argument
        f_idx = cmd.index("-f")
        format_str = cmd[f_idx + 1]

        assert "height<=360" in format_str, (
            f"Format selector does not target 360p: {format_str!r}\n"
            f"Expected 'height<=360' to appear in the format string.\n"
            f"The cache manager is downloading unnecessarily high-resolution video."
        )

        # Should NOT contain unbounded best quality
        assert "best[ext=mp4]/" not in format_str or "height<=360" in format_str, (
            f"Format selector may be requesting unbounded quality: {format_str!r}"
        )

    def test_download_to_work_dir_targets_360p(self):
        """_download_to_work_dir must also target 360p."""
        mgr = _make_cache_manager()
        captured_cmds = []

        with tempfile.TemporaryDirectory() as work_dir:
            fake_file = os.path.join(work_dir, "testVid.mp4")
            _make_valid_mp4(fake_file)

            def fake_run(cmd, **kwargs):
                captured_cmds.append(cmd)
                return MagicMock(returncode=0)

            with patch("video_cache_manager.subprocess.run", side_effect=fake_run):
                mgr._download_to_work_dir("testVid", work_dir)

        cmd = captured_cmds[0]
        f_idx = cmd.index("-f")
        format_str = cmd[f_idx + 1]

        assert "height<=360" in format_str, (
            f"_download_to_work_dir format selector does not target 360p: {format_str!r}"
        )
