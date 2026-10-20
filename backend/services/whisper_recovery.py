"""Bounded, cancellable Whisper recovery outside the API process."""
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time


async def recover_audio(service, video_id, language=None, progress_cb=None):
    from ..core.config import get_settings
    settings = get_settings()
    if not hasattr(service, "_whisper_slot"):
        service._whisper_slot = asyncio.Lock()

    async def report(message):
        if progress_cb:
            try:
                await progress_cb(message)
            except Exception:
                pass

    queued = time.monotonic()
    while True:
        try:
            await asyncio.wait_for(service._whisper_slot.acquire(), timeout=15)
            break
        except asyncio.TimeoutError:
            await report(f"Waiting for audio translation: {video_id} ({int(time.monotonic() - queued)}s queued)")

    proc = None
    reader = None
    try:
        await report(f"Downloading source audio for {video_id}...")
        with tempfile.TemporaryDirectory(prefix="whisper-recovery-") as work:
            result_path = Path(work) / "result.json"
            env = os.environ.copy()
            env.update({"VIDFUSION_WHISPER_WORKER": "1", "PYTHONUNBUFFERED": "1"})
            creation = asyncio.create_task(asyncio.create_subprocess_exec(
                sys.executable, "-m", "backend.services.whisper_recovery",
                video_id, language or "", str(result_path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                env=env, start_new_session=(os.name == "posix"),
            ))
            try:
                proc = await asyncio.shield(creation)
            except asyncio.CancelledError:
                # Cancellation during process creation must not lose the PID.
                proc = await creation
                raise
            stage = f"Preparing audio translation for {video_id}"

            async def read_progress():
                nonlocal stage
                async for raw in proc.stdout:
                    line = raw.decode(errors="replace").strip()
                    print(line, flush=True)
                    if line.startswith("[Transcript] Whisper chunk "):
                        stage = f"{video_id}: {line.removeprefix('[Transcript] ')}"
                        await report(stage)
                    elif "Loaded Whisper" in line:
                        stage = f"Translating source audio for {video_id}"
                        await report(stage)

            reader = asyncio.create_task(read_progress())
            started = time.monotonic()
            deadline = started + settings.TRANSCRIPT_SOURCE_TIMEOUT_SECONDS
            while proc.returncode is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=min(15, remaining))
                except asyncio.TimeoutError:
                    await report(f"{stage} — {int(time.monotonic() - started)}s elapsed")
            await reader
            if proc.returncode == 0 and result_path.exists():
                return json.loads(result_path.read_text())
            return None
    except asyncio.TimeoutError:
        await report(f"Audio translation timed out for {video_id}; checking caption fallback...")
        return None
    finally:
        # Stop torch and child downloads before freeing the inference slot.
        if proc is not None and proc.returncode is None:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
        if reader is not None and not reader.done():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        service._whisper_slot.release()


def main():
    import torch
    from .transcript_service import TranscriptService
    from ..core.config import get_settings
    torch.set_num_threads(get_settings().WHISPER_CPU_THREADS)
    video_id, language, output = sys.argv[1:]
    service = TranscriptService({"transcripts": None})
    result = service._fetch_whisper(video_id, language or None)
    Path(output).write_text(json.dumps(result))


if __name__ == "__main__":
    main()
