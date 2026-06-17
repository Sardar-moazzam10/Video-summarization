"""
Video Highlight Service — FFmpeg-based video clip extraction and assembly.

Pipeline (v2 — original-audio, precise-seek):
    1. Download source videos (via video_cache_manager.py)
    2. Trim + normalize each segment in ONE FFmpeg pass:
         - Two-stage seek: fast keyframe seek (-ss before -i) +
           precise sub-second offset (-ss after -i) → exact timestamp, not keyframe-aligned
         - Single re-encode to 1280x720 H.264 (no double encode)
         - Audio + video fade-in / fade-out at clip boundaries
    3. Concatenate clips with 0.4s black-frame + silence separator between each
       (visually signals topic change; preserves the "pause" feeling)
    4. Keep original speaker audio — NO TTS overlay on the video track.
       TTS narration remains as a SEPARATE audio file for the UI audio player.

Why original audio?
    The user's core requirement is voice-video sync: the face that is
    speaking matches what you hear, including natural pauses within a clip.
    Overlaying TTS destroys this — the original person's mouth moves while
    a synthetic voice says something different.
"""

import os
import shutil
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


FFMPEG_BIN = _resolve_binary("FFMPEG_PATH", "ffmpeg")
YTDLP_BIN  = _resolve_binary("YTDLP_PATH",  "yt-dlp")
NODE_BIN   = _resolve_binary("NODE_PATH",   "node")


class VideoService:
    """
    Generates video highlight reels from YouTube videos.

    v2 changes vs v1:
    - Trim + normalize combined into ONE FFmpeg pass (was two separate passes)
    - Two-stage precise seeking (keyframe fast-seek + sub-second offset)
    - Audio + video fade at clip boundaries
    - 0.4s black-frame separator between clips
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
        work_dir = tempfile.mkdtemp(prefix=f"highlight_{job_id}_")

        try:
            # Step 1: Trim + normalize in one precise FFmpeg pass
            if progress_callback:
                await progress_callback("Cutting highlight clips (precise seek)...")

            if progress_callback:
                await progress_callback(
                    f"Cutting {len(highlight_segments)} clips..."
                )
            clips = []
            for i, seg in enumerate(highlight_segments):
                clip = await self._trim_and_normalize_segment(
                    seg, video_paths, work_dir, i
                )
                if clip:
                    clips.append(clip)

            if not clips:
                raise Exception("No segments could be trimmed")

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
    ) -> Dict[str, str]:
        """Download videos using video_cache_manager, yt-dlp fallback."""
        import sys
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

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
                path = await self._download_single(vid, work_dir)
                if path:
                    video_paths[vid] = path
                    print(f"[Video] Downloaded {vid}: {path}")
            except Exception as e:
                print(f"[Video] Failed to download {vid}: {e}")

        return video_paths

    async def _download_single(self, video_id: str, work_dir: str) -> Optional[str]:
        """Download a single video using video_cache_manager or yt-dlp fallback."""
        try:
            from video_cache_manager import get_video_cache_manager
            cache_manager = get_video_cache_manager()
            path = await asyncio.wait_for(
                asyncio.to_thread(
                    cache_manager.download_and_cache_video, video_id, work_dir
                ),
                timeout=120.0,
            )
            return path
        except asyncio.TimeoutError:
            print(f"[Video] Cache manager timed out for {video_id} — falling back to yt-dlp")
        except Exception as e:
            print(f"[Video] Cache manager failed for {video_id}: {e}")

        url = f"https://www.youtube.com/watch?v={video_id}"
        output_template = os.path.join(work_dir, f"{video_id}.%(ext)s")
        cookies_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "cookies.txt"
        )

        cmd = [
            YTDLP_BIN,
            "--ffmpeg-location", self.ffmpeg,
            "--js-runtimes", f"node:{NODE_BIN}",
            "--remote-components", "ejs:github",
            "--no-check-certificates",
            "--socket-timeout", "30",
            "-f", "bestvideo[height<=360][ext=mp4]+bestaudio[abr<=64]"
                  "/best[height<=360][ext=mp4]/worst[ext=mp4]/worst",
            "--merge-output-format", "mp4",
            "-o", output_template,
            url,
        ]
        if os.path.exists(cookies_file):
            cmd.extend(["--cookies", cookies_file])

        print(f"[Video] Downloading {video_id} (360p max) via yt-dlp...")
        await asyncio.wait_for(
            asyncio.to_thread(
                subprocess.run, cmd, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            ),
            timeout=180.0,
        )

        for fname in os.listdir(work_dir):
            if fname.startswith(f"{video_id}."):
                return os.path.join(work_dir, fname)

        return None

    # ------------------------------------------------------------------
    # TRIM + NORMALIZE (combined, precise)
    # ------------------------------------------------------------------

    async def _trim_and_normalize_segment(
        self,
        seg: Dict,
        video_paths: Dict[str, str],
        work_dir: str,
        idx: int,
    ) -> Optional[str]:
        """
        Trim + normalize in ONE FFmpeg pass with exact timestamp precision.

        Two-stage seeking:
          Stage 1: -ss {start - 2s} BEFORE -i  → fast keyframe seek
          Stage 2: -ss {offset}     AFTER  -i  → precise sub-second correction

        Combined: keyframe decode (instant) + 2s forward decode (fast) =
        clip starts exactly at `start`, not at the previous keyframe.

        Also applies:
          - Scale/pad to 1280x720 (uniform format for concat)
          - Video fade-in + fade-out (0.3s each)
          - Audio fade-in + fade-out (0.3s each)
          - 30 fps output

        These fades give the viewer an auditory "breath" between clips,
        matching the natural pause structure of the original speaker.
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

        # Two-stage seek
        pre_seek       = max(0.0, start - 2.0)
        precise_offset = start - pre_seek   # ≤ 2.0 s

        # Fade duration: 0.3s or 10% of clip, whichever is shorter
        fade_d         = min(0.30, duration * 0.10)
        fade_out_start = max(0.0, duration - fade_d)

        vf = (
            f"scale=1280:720:force_original_aspect_ratio=decrease,"
            f"pad=1280:720:-1:-1:color=black,"
            f"fade=t=in:st=0:d={fade_d:.3f},"
            f"fade=t=out:st={fade_out_start:.3f}:d={fade_d:.3f}"
        )
        af = (
            f"afade=t=in:st=0:d={fade_d:.3f},"
            f"afade=t=out:st={fade_out_start:.3f}:d={fade_d:.3f}"
        )

        cmd = [
            self.ffmpeg, "-y",
            "-ss", f"{pre_seek:.3f}",         # fast keyframe seek
            "-i", src,
            "-ss", f"{precise_offset:.3f}",   # precise offset from keyframe
            "-t",  f"{duration:.3f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
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
        Concatenate clips with a 0.4s black-frame + silence separator between each.

        The separator serves as the "pause" the user expects between topic clips:
        when the original speaker stops one topic and starts another, you see
        a brief black frame before the next clip begins — mirroring the natural
        gap in the original video.
        """
        separator = await self._make_separator(work_dir)

        # Interleave: clip, sep, clip, sep, ..., clip  (no sep after last)
        interleaved = []
        for i, clip in enumerate(clip_files):
            interleaved.append(clip)
            if i < len(clip_files) - 1 and separator and os.path.exists(separator):
                interleaved.append(separator)

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
        Used as the visual "pause" between topic-change clips.
        Returns path on success, None if generation fails (concat skips it).
        """
        out = os.path.join(work_dir, "separator.mp4")
        cmd = [
            self.ffmpeg, "-y",
            "-f", "lavfi",
            "-i", "color=c=black:size=1280x720:rate=30:duration=0.4",
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "0.4",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
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
