"""
Video Highlight Service — FFmpeg-based video clip extraction and assembly.

Pipeline (v2 — original-audio, precise-seek):
    1. Download source videos (via video_cache_manager.py)
    2. Trim + normalize each segment in ONE FFmpeg pass:
         - Single accurate input seek (-ss before -i) → exact timestamp, not
           keyframe-aligned, and PTS reset to 0 so fade timings line up
         - Single re-encode to 1280x720 H.264 (no double encode)
         - Hard video cut; short audio de-click fade only
    3. Concatenate clips back to back — no black-frame separator, and since the
       video fade was removed, no fade to black either (see
       _concat_with_transitions and _trim_and_normalize_segment)
    4. Keep original speaker audio — NO TTS overlay on the video track.
       TTS narration remains as a SEPARATE audio file for the UI audio player.

Why original audio?
    The user's core requirement is voice-video sync: the face that is
    speaking matches what you hear, including natural pauses within a clip.
    Overlaying TTS destroys this — the original person's mouth moves while
    a synthetic voice says something different.
"""

from .acquisition_service import append_event
import os
import sys
import shutil
import importlib.util
import subprocess
import tempfile
import asyncio
from typing import List, Dict, Optional, Callable, Awaitable
from pathlib import Path


def _resolve_binary(env_name: str, default_name: str) -> str:
    # Read from pydantic settings first (loaded from .env), fall back to raw os.getenv
    try:
        from ..core.config import get_settings
        val = getattr(get_settings(), env_name, "") or os.getenv(env_name, "")
    except Exception:
        val = os.getenv(env_name, "")
    if val and os.path.isfile(val):
        return val
    return shutil.which(default_name) or default_name


def _resolve_ytdlp_cmd() -> List[str]:
    """
    yt-dlp as a command *prefix* rather than a single binary path.

    Order: explicit YTDLP_PATH override → `<current interpreter> -m yt_dlp` →
    PATH lookup. The module form makes the venv's yt-dlp reachable even when
    venv/bin is absent from the server process's PATH.
    """
    explicit = _resolve_binary("YTDLP_PATH", "")
    if explicit and os.path.isfile(explicit):
        return [explicit]
    if importlib.util.find_spec("yt_dlp") is not None:
        return [sys.executable, "-m", "yt_dlp"]
    return [shutil.which("yt-dlp") or "yt-dlp"]


FFMPEG_BIN = _resolve_binary("FFMPEG_PATH", "ffmpeg")
YTDLP_CMD  = _resolve_ytdlp_cmd()
YTDLP_BIN  = YTDLP_CMD[0]  # retained for logging / back-compat
NODE_BIN   = _resolve_binary("NODE_PATH",   "node")

# Bounded concurrency for per-clip trim/normalize (each is one ffmpeg
# subprocess: decode+scale/pad+encode). The clip loop used to run strictly
# sequentially — one ffmpeg process at a time — which measurably dominated
# highlight-reel latency (a real 33-clip job spent 155.8s here, the single
# largest contributor to total job time).
#
# Chosen from a real benchmark (33 real clips, same source video) measuring
# wall time / CPU / memory at 1, 2, 4, 6, 8 concurrent workers on this class
# of hardware (4-core/8-thread, memory-constrained):
#   1: 114.5s   2: 122.2s (slower — noise/contention)   4: 111.9s (~flat)
#   6: 96.8s (-15% vs N=1)   8: 74.5s (-35%, but +32% more memory than N=6)
# CPU is already ~94-97% saturated by N=4, so 4/6/8 don't meaningfully differ
# in CPU headroom — the real differentiator is memory, which scales ~linearly
# with worker count (184MB at N=1 -> 1273MB peak at N=8). No correctness
# issues (duration, A/V sync, black frames) at any tested N. 6 was chosen as
# the best speed/memory balance for this machine, not the outright fastest.
MAX_CONCURRENT_CLIP_ENCODES = 6


class VideoService:
    """
    Generates video highlight reels from YouTube videos.

    v2 changes vs v1:
    - Trim + normalize combined into ONE FFmpeg pass (was two separate passes)
    - Accurate single-stage input seeking (PTS-reset, fade-safe)
    - Hard cut on video; 0.04s audio fade only (de-click, not a transition)
    - Clips concatenated back to back (black-frame separator removed)
    - Original speaker audio preserved (TTS not overlaid on video)
    """

    def __init__(self):
        self.ffmpeg = FFMPEG_BIN
        self.output_dir = Path("audio_cache/highlights")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_highlight_reel(
        self,
        job_id: str,
        highlight_segments: List[Dict],
        video_paths: Dict[str, str],
        audio_path: Optional[str] = None,   # kept for API compat; not overlaid
        progress_callback: Optional[Callable[[str], Awaitable]] = None,
    ) -> str:
        """
        Main entry: trim, normalize, concatenate.  Original audio is preserved.

        `audio_path` is accepted for API compatibility but is intentionally NOT
        overlaid onto the video.  The TTS MP3 is served as a separate audio
        player in the UI.  Overlaying TTS would replace the original speaker's
        voice, breaking voice-video sync.

        Args:
            job_id:             Unique job identifier.
            highlight_segments: [{video_id, start_time, end_time, ...}]
            video_paths:        Dict mapping video_id → local file path.
            audio_path:         Ignored (kept for API compat).
            progress_callback:  Async callback for stage messages.

        Returns:
            Path to the final highlight reel MP4 (original speaker audio).
        """
        from .clip_manifest import validate_manifest
        from types import MappingProxyType
        # Freeze the final handoff, including source and interval, before any
        # asynchronous trim work starts. Workers cannot mutate manifest entries.
        highlight_segments = tuple(MappingProxyType(dict(clip)) for clip in highlight_segments)
        validate_manifest(highlight_segments, video_paths)
        work_dir = tempfile.mkdtemp(prefix=f"highlight_{job_id}_")

        try:
            # Step 1: Trim + normalize in one precise FFmpeg pass
            if progress_callback:
                await progress_callback("Cutting highlight clips (precise seek)...")

            if progress_callback:
                await progress_callback(
                    f"Cutting {len(highlight_segments)} clips..."
                )
            clips = await self._trim_segments_bounded(
                highlight_segments, video_paths, work_dir
            )

            if not clips:
                raise Exception("No segments could be trimmed")
            if len(clips) != len(highlight_segments):
                raise RuntimeError("Rendering failed: selected clips could not all be trimmed; manifest preserved")

            # Step 2: Concatenate with 0.4s black-frame transitions between clips
            if progress_callback:
                await progress_callback(
                    f"Stitching {len(clips)} clips with topic-change transitions..."
                )
            concat_path = await self._concat_with_transitions(clips, job_id, work_dir)

            # Step 3: Copy to permanent output location (original audio, no TTS overlay)
            final_path = str(self.output_dir / f"highlight_{job_id}.mp4")
            shutil.copy2(concat_path, final_path)

            print(f"[Video] Highlight reel ready (original audio): {final_path}")
            return final_path

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # DOWNLOAD
    # ------------------------------------------------------------------

    async def download_videos(
        self,
        video_ids: List[str],
        job_id: str = "",
        progress_callback: Optional[Callable[[str], Awaitable]] = None,
        source_duration_seconds: Optional[float] = None,
    ) -> Dict[str, str]:
        """Download videos using video_cache_manager, yt-dlp fallback.

        Args:
            video_ids:                List of YouTube video IDs.
            job_id:                   Used to name the download work directory.
            progress_callback:        Async callable for status messages.
            source_duration_seconds:  Known duration of the source content, used
                                      to compute a bounded per-video download
                                      timeout.  Longer videos get a larger window;
                                      unknown durations get a safe default.
        """
        import sys
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        # Per-video timeout: 0.5x the source duration plus a 120s fixed margin
        # (for startup, format negotiation, and merge).  This bounds the download
        # to something proportional to the content length rather than a fixed wall
        # that is right for 20-min videos and wrong for 95-min ones.
        #
        # Floor at 300s (enough for ~20 min at typical YouTube 360p speed).
        # Ceiling at 3600s (1 hour — a 120-min video at half-speed should finish).
        if source_duration_seconds and source_duration_seconds > 0:
            _per_video_timeout = max(
                300.0,
                min(3600.0, source_duration_seconds * 0.5 + 120.0),
            )
        else:
            _per_video_timeout = 600.0  # 10-min default when duration unknown

        video_paths = {}
        if job_id:
            work_dir = str(Path("audio_cache/video_downloads") / job_id)
            os.makedirs(work_dir, exist_ok=True)
        else:
            work_dir = tempfile.mkdtemp(prefix="video_dl_")

        for i, vid in enumerate(video_ids):
            if progress_callback:
                await progress_callback(f"Downloading video {i + 1}/{len(video_ids)}...")
            try:
                path = await self._download_single(vid, work_dir, timeout=_per_video_timeout)
                if path:
                    video_paths[vid] = path
                    print(f"[Video] Downloaded {vid}: {path}")
            except Exception as e:
                print(f"[Video] Failed to download {vid}: {e}")

        return video_paths

    async def _download_single(
        self, video_id: str, work_dir: str, timeout: float = 600.0
    ) -> Optional[str]:
        """Download a single video using video_cache_manager or yt-dlp fallback.

        Args:
            video_id:   YouTube video ID.
            work_dir:   Directory to write the downloaded file.
            timeout:    Per-video wall-clock budget in seconds.  The cache
                        manager attempt gets half this budget; the yt-dlp
                        fallback gets the remaining half.  This ensures both
                        together stay within the caller's expectation and that
                        neither can silently exhaust the whole budget on its own.
        """
        # Split the budget between the two download paths so neither can
        # monopolise the full timeout while still leaving room for both.
        _cache_timeout   = timeout * 0.4   # 40% for the cache manager (fast path)
        _ytdlp_timeout   = timeout * 0.6   # 60% for the yt-dlp fallback

        try:
            from video_cache_manager import get_video_cache_manager
            cache_manager = get_video_cache_manager()
            await append_event(
                source_id=video_id,
                operation="video_download",
                phase="attempted",
                method="video_cache_manager",
                outcome_code="started",
            )
            path = await asyncio.wait_for(
                asyncio.to_thread(
                    cache_manager.download_and_cache_video, video_id, work_dir
                ),
                timeout=_cache_timeout,
            )
            await append_event(
                source_id=video_id,
                operation="video_download",
                phase="succeeded",
                method="video_cache_manager",
                outcome_code="success",
            )
            return path
        except asyncio.TimeoutError:
            await append_event(
                source_id=video_id,
                operation="video_download",
                phase="failed",
                method="video_cache_manager",
                outcome_code="timeout",
            )
            print(f"[Video] Cache manager timed out ({_cache_timeout:.0f}s) for {video_id} "
                  f"— falling back to yt-dlp")
        except Exception as e:
            await append_event(
                source_id=video_id,
                operation="video_download",
                phase="failed",
                method="video_cache_manager",
                outcome_code="error",
            )
            print(f"[Video] Cache manager failed for {video_id}: {e}")

        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = os.path.join(work_dir, f"{video_id}.%(ext)s")
        cookies_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "cookies.txt"
        )

        cmd = [
            *YTDLP_CMD,
            "--ffmpeg-location", self.ffmpeg,
            "--js-runtimes", f"node:{NODE_BIN}",
            "--remote-components", "ejs:github",
            "--no-check-certificates",
            "--socket-timeout", "30",
            # Abort if YouTube throttles below 100 KB/s — the signature of a
            # missing PO Token / stale cookies.  At 0.1 MB/s a 95-min 360p
            # video (~700 MB) takes ~2 hours; better to fail fast and surface
            # the authentication problem.
            "--throttled-rate", "100K",
            "-f", "bestvideo[height<=360][ext=mp4]+bestaudio[abr<=64]"
                  "/best[height<=360][ext=mp4]/worst[ext=mp4]/worst",
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ]
        if os.path.exists(cookies_file):
            cmd.extend(["--cookies", cookies_file])

        print(f"[Video] Downloading {video_id} (360p max, timeout={_ytdlp_timeout:.0f}s) via yt-dlp...")
        await append_event(
            source_id=video_id,
            operation="video_download",
            phase="attempted",
            method="yt_dlp",
            outcome_code="started",
        )
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run, cmd, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    # Hard subprocess timeout: if asyncio cancels the to_thread
                    # wrapper the OS will also kill yt-dlp, not just the task.
                    timeout=_ytdlp_timeout,
                ),
                timeout=_ytdlp_timeout + 5,  # asyncio wrapper adds a small margin
            )
        except asyncio.TimeoutError:
            await append_event(
                source_id=video_id,
                operation="video_download",
                phase="failed",
                method="yt_dlp",
                outcome_code="timeout",
            )
            print(f"[Video] yt-dlp timed out ({_ytdlp_timeout:.0f}s) for {video_id}")
            return None
        except subprocess.CalledProcessError as e:
            await append_event(
                source_id=video_id,
                operation="video_download",
                phase="failed",
                method="yt_dlp",
                outcome_code="error",
            )
            err = (e.stderr or b"").decode(errors="replace")[-400:] if e.stderr else ""
            print(f"[Video] yt-dlp failed for {video_id}: {err}")
            return None

        for fname in os.listdir(work_dir):
            if fname.startswith(f"{video_id}."):
                await append_event(
                    source_id=video_id,
                    operation="video_download",
                    phase="succeeded",
                    method="yt_dlp",
                    outcome_code="success",
                )
                fsize_mb = os.path.getsize(os.path.join(work_dir, fname)) / (1024 * 1024)
                print(f"[Video] yt-dlp download complete: {fname} ({fsize_mb:.1f} MB)")
                return os.path.join(work_dir, fname)

        return None

    # ------------------------------------------------------------------
    # TRIM + NORMALIZE (combined, precise)
    # ------------------------------------------------------------------

    async def _trim_segments_bounded(
        self,
        highlight_segments: List[Dict],
        video_paths: Dict[str, str],
        work_dir: str,
    ) -> List[str]:
        """
        Trim + normalize every segment with at most MAX_CONCURRENT_CLIP_ENCODES
        ffmpeg processes in flight at once — see that constant's comment for
        why 6 and not "as many as possible".

        Segment order is preserved in the returned list regardless of which
        clip's ffmpeg process happens to finish first (concat depends on
        this order matching highlight_segments' order). A failed clip
        (_trim_and_normalize_segment returning None) is dropped, same as the
        prior sequential loop.
        """
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLIP_ENCODES)

        async def _bounded(i: int, seg: Dict) -> Optional[str]:
            async with semaphore:
                return await self._trim_and_normalize_segment(seg, video_paths, work_dir, i)

        results = await asyncio.gather(
            *[_bounded(i, seg) for i, seg in enumerate(highlight_segments)]
        )
        return [clip for clip in results if clip]

    async def _trim_and_normalize_segment(
        self,
        seg: Dict,
        video_paths: Dict[str, str],
        work_dir: str,
        idx: int,
    ) -> Optional[str]:
        """
        Trim + normalize in ONE FFmpeg pass with exact timestamp precision.

        Seeking:
          A single input-side `-ss {start}` before `-i`.  Since FFmpeg 2.1 this
          is frame-accurate when re-encoding: FFmpeg seeks to the preceding
          keyframe, then decodes and discards up to `start` internally.

          It also resets the stream PTS to 0 at `start`, so the filtergraph
          clock and the output clock are the same clock.  That is what makes
          the fade timings below correct — see the fade comment.

        Also applies:
          - Scale/pad to 1280x720 (uniform format for concat)
          - Audio fade-in + fade-out of 0.04s (click suppression only)
          - 30 fps output
        """
        vid = seg.get("video_id")
        if not vid or vid not in video_paths:
            print(f"[Video] Segment {idx}: video {vid!r} not in downloaded paths")
            return None

        src = video_paths[vid]
        out = os.path.join(work_dir, f"clip_{idx:04d}.mp4")

        start    = float(seg["start_time"])
        duration = float(seg["end_time"]) - start

        if duration < 0.5:
            return None

        # VIDEO: hard cut, no fade.
        #
        # The video used to fade in and out over 0.15s at every clip boundary.
        # Measured on a rendered 5-minute reel, blackdetect found a black run at
        # 7 of the 8 joins — 28.85s, 109.89s, 171.65s, 191.89s, 232.99s,
        # 254.19s, 276.92s, against joins at 28.84, 109.85, 171.57, 191.79,
        # 232.87, 254.01, 276.75 — each 0.07-0.10s, which is 2-3 frames of black
        # flashing between every pair of clips. A fade "to black" is a fade to
        # black however short it is; on a highlight reel it reads as a glitch,
        # and a hard cut is what the format normally uses anyway.
        #
        # AUDIO: a short fade is kept and shortened to 0.04s. Splicing raw PCM
        # at an arbitrary sample produces an audible click; 0.04s (~2 frames)
        # removes it without being perceptible as a fade, and is short enough
        # that it cannot clip the start or end of a word. Segments already begin
        # and end on sentence boundaries, so it lands in a natural pause.
        #
        # `st=` is measured on the FILTERGRAPH clock, which is zero-based at
        # `start` only because the seek above is a single input-side -ss. Keep
        # the seek single-stage or these offsets stop lining up.
        fade_d         = min(0.04, duration * 0.05)
        fade_out_start = max(0.0, duration - fade_d)

        vf = (
            f"scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:-1:-1:color=black,"
            f"tpad=stop_mode=clone:stop_duration=2"
        )
        af = (
            f"afade=t=in:st=0:d={fade_d:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_d:.3f},"
            f"apad"
        )

        cmd = [
            self.ffmpeg, "-y",
            "-ss", f"{start:.3f}",            # accurate input seek; resets PTS to 0
            "-i", src,
            "-t",  f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-r", "30",
            "-vf", vf,
            "-af", af,
            "-movflags", "+faststart",
            out,
        ]

        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=180,
            )
            if result.returncode != 0:
                err = result.stderr.decode(errors="replace")[-400:]
                print(f"[Video] Clip {idx} (start={start:.1f}s) failed: {err}")
                return None
            return out
        except subprocess.TimeoutExpired:
            print(f"[Video] Timeout encoding clip {idx} (start={start:.1f}s) — skipping")
            return None
        except Exception as e:
            print(f"[Video] Error encoding clip {idx}: {e}")
            return None

    # ------------------------------------------------------------------
    # CONCAT WITH TRANSITIONS
    # ------------------------------------------------------------------

    async def _concat_with_transitions(
        self,
        clip_files: List[str],
        job_id: str,
        work_dir: str,
    ) -> str:
        """
        Concatenate clips back to back.

        The 0.4s black-frame separator that used to sit between clips has been
        removed. Each clip already carries its own fade-in/fade-out, so the
        separator stacked on top of them: fade-out (0.3s) + black (0.4s) +
        fade-in (0.3s) put roughly a second of darkness between every clip —
        about 24s of a 25-clip reel — which read as a black-screen bug rather
        than the intended "pause". The fades alone give a clean transition.

        _make_separator() is retained (unused) so the behaviour can be restored
        by re-interleaving its output here.
        """
        # Clips concatenate directly — no separator frames.
        interleaved = list(clip_files)

        list_path = os.path.join(work_dir, "concat.txt")
        with open(list_path, "w") as f:
            for path in interleaved:
                f.write(f"file '{path}'\n")

        output = os.path.join(work_dir, f"concat_{job_id}.mp4")
        cmd = [
            self.ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            output,
        ]
        result = await asyncio.to_thread(
            subprocess.run, cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=300,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace")[-500:]
            raise RuntimeError(f"FFmpeg concat failed: {err}")
        return output

    async def _make_separator(self, work_dir: str) -> Optional[str]:
        """
        Generate a 0.4s black-frame + silence MP4.

        NOT CURRENTLY CALLED — see _concat_with_transitions(). Kept so the
        black-frame "pause" between topic clips can be restored by interleaving
        this file back into the concat list.

        Returns path on success, None if generation fails.
        """
        out = os.path.join(work_dir, "separator.mp4")
        cmd = [
            self.ffmpeg, "-y",
            "-f", "lavfi",
            "-i", "color=c=black:size=1280x720:rate=30:duration=0.4",
            "-f", "lavfi",
            "-i", "anullsrc=r=48000:cl=stereo",
            "-t", "0.4",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
            "-shortest",
            out,
        ]
        try:
            result = await asyncio.to_thread(
                subprocess.run, cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=30,
            )
            if result.returncode == 0 and os.path.exists(out):
                return out
        except Exception as e:
            print(f"[Video] Separator generation failed: {e}")
        return None


# =====================================================
# SINGLETON
# =====================================================

_video_service = None


def get_video_service() -> VideoService:
    global _video_service
    if _video_service is None:
        _video_service = VideoService()
    return _video_service
