with open('backend/api/merge.py', 'r') as f:
    content = f.read()

# 1. Add imports at the very top (after APIRouter import)
content = content.replace(
    'from fastapi import APIRouter',
    'from ..services.acquisition_service import create_shadow_job_decisions, set_observation_context, reset_observation_context, finalize_shadow_manifest, append_event, load_job_decision_ids\nfrom fastapi import APIRouter'
)

# 2. Add context creation
content = content.replace(
'''    try:
        job = _active_jobs.get(job_id)
        if not job:
            return
        if not getattr(job, "job_started_at", None):
            job.job_started_at = datetime.utcnow()

        pipeline_timings = {name: 0.0 for name in (''',
'''    acq_token = None
    try:
        job = _active_jobs.get(job_id)
        if not job:
            return
        if not getattr(job, "job_started_at", None):
            job.job_started_at = datetime.utcnow()

        decisions = await create_shadow_job_decisions(
            job_id=job.job_id,
            user_id=job.user_id or "anonymous",
            source_ids=job.video_ids,
        )
        acq_token = set_observation_context(
            job_id=job.job_id,
            user_id=job.user_id or "anonymous",
            decision_ids=decisions,
        )

        pipeline_timings = {name: 0.0 for name in ('''
)

# 3. Finalize manifest in finally
content = content.replace(
'''    finally:
        # Clean up memory after some time
        await asyncio.sleep(300)  # Keep in memory for 5 minutes''',
'''    finally:
        if acq_token is not None:
            try:
                import asyncio
                task = asyncio.current_task()
                if not (task and task.cancelled()):
                    await finalize_shadow_manifest(
                        job_id,
                        reason="job_completed" if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL_SUCCESS, JobStatus.VIDEO_READY) else "job_failed"
                    )
            except BaseException:
                pass
            reset_observation_context(acq_token)
        # Clean up memory after some time
        try:
            import asyncio
            task = asyncio.current_task()
            if not (task and task.cancelled()):
                await asyncio.sleep(300)  # Keep in memory for 5 minutes
        except BaseException:
            pass'''
)

# 4. Derived media delivery (get_job_video)
content = content.replace(
'''    video_path = job_data.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(404, "Video highlight reel not available")

    return FileResponse(''',
'''    video_path = job_data.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(404, "Video highlight reel not available")

    decision_ids = await load_job_decision_ids(job_id)
    acq_token = set_observation_context(
        job_id=job_id,
        user_id=job_data.get("user_id") or "anonymous",
        decision_ids=decision_ids
    )
    try:
        for vid in (job_data.get("used_video_ids") or job_data.get("video_ids") or []):
            await append_event(
                source_id=vid,
                operation="derived_media_deliver",
                phase="succeeded",
                method="http_download",
                outcome_code="success",
            )
    finally:
        reset_observation_context(acq_token)

    return FileResponse('''
)

# 5. Derived media delivery (get_job_audio)
content = content.replace(
'''    audio_path = job_data.get("audio_path")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(404, "Audio not available")

    return FileResponse(''',
'''    audio_path = job_data.get("audio_path")
    if not audio_path or not os.path.exists(audio_path):
        raise HTTPException(404, "Audio not available")

    decision_ids = await load_job_decision_ids(job_id)
    acq_token = set_observation_context(
        job_id=job_id,
        user_id=job_data.get("user_id") or "anonymous",
        decision_ids=decision_ids
    )
    try:
        for vid in (job_data.get("used_video_ids") or job_data.get("video_ids") or []):
            await append_event(
                source_id=vid,
                operation="derived_media_deliver",
                phase="succeeded",
                method="http_download",
                outcome_code="success",
            )
    finally:
        reset_observation_context(acq_token)

    return FileResponse('''
)

# 6. Keyframes extraction
content = content.replace(
'''            try:
                visual_keyframes = await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_keyframes_for_segments, vid, vid_path, transcript_groups
                    ),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                print(f"[Video] Keyframe extraction timed out for {vid} — skipping visual stage")
                visual_keyframes = []''',
'''            try:
                await append_event(
                    source_id=vid,
                    operation="keyframe_generate",
                    phase="attempted",
                    method="opencv_extraction",
                    outcome_code="started",
                )
                visual_keyframes = await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_keyframes_for_segments, vid, vid_path, transcript_groups
                    ),
                    timeout=90.0,
                )
                await append_event(
                    source_id=vid,
                    operation="keyframe_generate",
                    phase="succeeded",
                    method="opencv_extraction",
                    outcome_code="success",
                )
            except asyncio.TimeoutError:
                await append_event(
                    source_id=vid,
                    operation="keyframe_generate",
                    phase="failed",
                    method="opencv_extraction",
                    outcome_code="timeout",
                )
                print(f"[Video] Keyframe extraction timed out for {vid} — skipping visual stage")
                visual_keyframes = []'''
)

# 7. Derived media generation (highlight reel)
content = content.replace(
'''                t_render_start = perf_counter()
                video_path = await timed_stage("rendering", video_svc.generate_highlight_reel(
                    job_id=job.job_id,
                    highlight_segments=highlight_segments_result,
                    video_paths=video_paths,
                    audio_path=None,   # never overlaid; reel keeps source audio
                    progress_callback=video_progress,
                ))
                t_render_dur = round(perf_counter() - t_render_start, 3)''',
'''                t_render_start = perf_counter()
                rendered_sources = set(h.get("video_id") for h in highlight_segments_result if h.get("video_id"))
                for vid in rendered_sources:
                    await append_event(
                        source_id=vid,
                        operation="derived_media_generate",
                        phase="attempted",
                        method="ffmpeg_concat",
                        outcome_code="started",
                    )
                video_path = await timed_stage("rendering", video_svc.generate_highlight_reel(
                    job_id=job.job_id,
                    highlight_segments=highlight_segments_result,
                    video_paths=video_paths,
                    audio_path=None,   # never overlaid; reel keeps source audio
                    progress_callback=video_progress,
                ))
                for vid in rendered_sources:
                    await append_event(
                        source_id=vid,
                        operation="derived_media_generate",
                        phase="succeeded" if video_path else "failed",
                        method="ffmpeg_concat",
                        outcome_code="success" if video_path else "error",
                    )
                t_render_dur = round(perf_counter() - t_render_start, 3)'''
)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
