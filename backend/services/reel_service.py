"""
VidFusion Reel Studio Service.
Generates 9:16 vertical shorts/reels with blurred canvas, license verification,
and optional EdgeTTS neural voiceovers.
"""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Optional
import edge_tts

VOICE_MAP = {
    "en": "en-US-GuyNeural",
    "en-female": "en-US-JennyNeural",
    "ur": "ur-PK-UzmaNeural",
    "ur-male": "ur-PK-AsadNeural",
    "hi": "hi-IN-SwaraNeural",
    "hi-male": "hi-IN-MadhurNeural",
}


class ReelService:
    def __init__(self, output_dir: Optional[str] = None):
        self.output_dir = Path(output_dir or "audio_cache/reels")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg = shutil.which("ffmpeg") or "ffmpeg"

    def get_reel_candidates(self, job_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract the top 3-4 viral moments from a completed job's chapters/takeaways.
        """
        candidates: List[Dict[str, Any]] = []
        rich_output = job_data.get("rich_output") or {}
        chapters = rich_output.get("chapters") or []
        segments = job_data.get("highlight_segments") or []
        rights_snap = job_data.get("rights_snapshot") or {}
        sources_rights = rights_snap.get("sources") or []

        # Map video rights
        rights_map: Dict[str, bool] = {}
        for s in sources_rights:
            vid = s.get("source_id") or s.get("video_id")
            plat = s.get("evidence", {}).get("platform", {})
            lic = plat.get("status_license") or s.get("license")
            if vid:
                rights_map[vid] = (lic == "creativeCommon")

        # Fallback to job-level publication status if individual source not mapped
        aggregate_eligible = (
            job_data.get("publication_gate_status") == "eligible_by_recorded_rights"
            or job_data.get("preview_allowed") is True and job_data.get("download_allowed") is True
        )

        # 1. First preference: Rich Chapters
        for i, ch in enumerate(chapters):
            title = ch.get("title") or f"Highlight Moment {i + 1}"
            text = ch.get("text") or ""
            start = ch.get("timestamp_seconds")
            vid = ch.get("video_id") or (job_data.get("video_ids") or [""])[0]

            is_cc = rights_map.get(vid, aggregate_eligible)

            # Estimate duration for the candidate: target ~30s-40s
            duration = 35.0
            if start is not None:
                candidates.append({
                    "id": f"moment_{i}",
                    "index": i,
                    "title": title,
                    "text": text,
                    "start_time": float(start),
                    "duration_seconds": duration,
                    "video_id": vid,
                    "is_cc_by": is_cc,
                    "license_label": "⚖️ CC BY (Safe to Publish)" if is_cc else "🔒 Standard License (Fair-Use Transformative)",
                    "safe_to_export": is_cc,
                })
            if len(candidates) >= 4:
                break

        # 2. Fallback to highlight_segments if chapters have no timestamps
        if not candidates and segments:
            for i, seg in enumerate(segments[:4]):
                start = float(seg.get("start_time", 0.0))
                end = float(seg.get("end_time", start + 30.0))
                dur = min(max(end - start, 15.0), 60.0)
                vid = seg.get("video_id") or ""
                text = seg.get("text") or ""
                is_cc = rights_map.get(vid, aggregate_eligible)

                candidates.append({
                    "id": f"moment_{i}",
                    "index": i,
                    "title": f"Key Clip {i + 1}",
                    "text": text or f"Highlight clip from video {vid[:6]}",
                    "start_time": start,
                    "duration_seconds": round(dur, 1),
                    "video_id": vid,
                    "is_cc_by": is_cc,
                    "license_label": "⚖️ CC BY (Safe to Publish)" if is_cc else "🔒 Standard License (Fair-Use Transformative)",
                    "safe_to_export": is_cc,
                })

        # 3. Ultimate fallback: Top 30s slice from the rendered highlight reel
        if not candidates and job_data.get("video_path") and os.path.exists(job_data["video_path"]):
            candidates.append({
                "id": "moment_0",
                "index": 0,
                "title": "Top Highlight Moment",
                "text": rich_output.get("tldr") or "Top key insight from the merged highlight video.",
                "start_time": 0.0,
                "duration_seconds": 30.0,
                "video_id": (job_data.get("video_ids") or [""])[0],
                "is_cc_by": aggregate_eligible,
                "license_label": "⚖️ CC BY (Safe to Publish)" if aggregate_eligible else "🔒 Standard License (Fair-Use Transformative)",
                "safe_to_export": aggregate_eligible,
            })

        return candidates

    async def generate_voiceover(self, text: str, voice_lang: str, output_path: str, duration_budget: float = 30.0) -> str:
        """
        Generate Studio Neural Voiceover using Edge-TTS with strict word budgeting.
        """
        voice = VOICE_MAP.get(voice_lang, VOICE_MAP["en"])
        
        # Word budget: ~2.4 words per second to prevent speech overrun
        max_words = max(15, int(duration_budget * 2.3))
        words = text.strip().split()
        if len(words) > max_words:
            narration_text = " ".join(words[:max_words]).rstrip(",;:-") + "."
        else:
            narration_text = text.strip()

        if not narration_text:
            narration_text = "Here is the key insight from this highlight video."

        comm = edge_tts.Communicate(narration_text, voice)
        await comm.save(output_path)
        return output_path

    async def render_reel(
        self,
        job_id: str,
        job_data: Dict[str, Any],
        candidate_idx: int = 0,
        audio_mode: str = "original",
        voice_lang: str = "en",
    ) -> Dict[str, Any]:
        """
        Render a 1080x1920 vertical reel with 9:16 split-blur canvas.
        Fast, deterministic, and FastStart-enabled.
        """
        candidates = self.get_reel_candidates(job_data)
        if not candidates:
            raise RuntimeError("No candidate moments found for this job.")

        if candidate_idx < 0 or candidate_idx >= len(candidates):
            candidate = candidates[0]
        else:
            candidate = candidates[candidate_idx]

        # Determine source video file
        # Priority: Rendered highlight reel or downloaded video source
        source_video = job_data.get("video_path")
        is_from_highlight_reel = True

        if not source_video or not os.path.exists(source_video):
            # Check source video cache for this candidate's video_id
            vid = candidate.get("video_id")
            cache_path = os.path.join("audio_cache", "video_cache", f"{vid}.mp4")
            dl_path = os.path.join("audio_cache", "video_downloads", job_id, f"{vid}.mp4")
            if os.path.exists(cache_path):
                source_video = cache_path
                is_from_highlight_reel = False
            elif os.path.exists(dl_path):
                source_video = dl_path
                is_from_highlight_reel = False
            else:
                raise RuntimeError("Source video file is not available on disk.")

        start_time = candidate["start_time"]
        duration = candidate["duration_seconds"]

        # If pulling from the already merged highlight reel, ensure start_time doesn't exceed reel duration
        if is_from_highlight_reel:
            start_time = max(0.0, min(start_time, 15.0))

        reel_filename = f"reel_{job_id}_{candidate['id']}_{audio_mode}.mp4"
        output_path = str(self.output_dir / reel_filename)

        # Temporary work folder for audio and intermediate files
        work_dir = Path("audio_cache") / "reels" / f"tmp_{job_id}_{candidate['id']}"
        work_dir.mkdir(parents=True, exist_ok=True)
        voiceover_path = str(work_dir / "voiceover.mp3")

        try:
            # Step 1: Handle Voiceover if requested
            has_voiceover = False
            if audio_mode == "voiceover":
                script = candidate.get("text") or candidate.get("title") or "Key video highlight summary."
                await self.generate_voiceover(script, voice_lang, voiceover_path, duration_budget=duration)
                if os.path.exists(voiceover_path) and os.path.getsize(voiceover_path) > 1000:
                    has_voiceover = True

            # Step 2: Build FFmpeg 9:16 Filter Graph
            # Split-blur canvas: ultra-fast silky blurred background + sharp foreground centered
            filter_complex = (
                "[0:v]scale=72:128,scale=720:1280:flags=bicubic[bg];"
                "[0:v]scale=720:-1[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )

            cmd = [
                self.ffmpeg, "-y",
                "-ss", f"{start_time:.3f}",
                "-i", source_video,
            ]

            if has_voiceover:
                cmd.extend(["-i", voiceover_path])
                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[v]",
                    "-map", "1:a:0",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                    "-shortest",
                ])
            else:
                cmd.extend([
                    "-filter_complex", filter_complex,
                    "-map", "[v]",
                    "-map", "0:a:0?",
                    "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                    "-t", f"{duration:.3f}",
                ])

            cmd.extend([
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-movflags", "+faststart",
                output_path,
            ])

            # Run FFmpeg
            proc = await asyncio.to_thread(
                subprocess.run, cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                timeout=120,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode(errors="replace")[-400:]
                raise RuntimeError(f"Reel rendering failed: {err}")

            return {
                "reel_id": f"{candidate['id']}_{audio_mode}",
                "job_id": job_id,
                "video_url": f"/api/v1/reel/{job_id}/download/{candidate['id']}_{audio_mode}",
                "candidate": candidate,
                "audio_mode": audio_mode,
                "voice_language": voice_lang if has_voiceover else "original",
                "duration_seconds": duration,
                "aspect_ratio": "9:16",
                "safe_to_export": candidate["safe_to_export"],
            }

        finally:
            shutil.rmtree(work_dir, ignore_errors=True)


_REEL_SERVICE = ReelService()

def get_reel_service() -> ReelService:
    return _REEL_SERVICE
