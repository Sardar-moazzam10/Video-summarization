with open('backend/api/merge.py', 'r') as f:
    content = f.read()

replacement = '''            try:
                if job.generate_audio and video_path:
                    rendered_sources = set(h.get("video_id") for h in highlight_segments_result if h.get("video_id"))
                    for vid in rendered_sources:
                        await append_event(source_id=vid, operation="derived_media_generate", phase="attempted", method="ffmpeg_mp3_extract", outcome_code="started")
                    
                    audio_path = await asyncio.to_thread(
                        _extract_audio_from_reel, video_path, job.job_id
                    )
                    
                    for vid in rendered_sources:
                        await append_event(source_id=vid, operation="derived_media_generate", phase="succeeded" if audio_path else "failed", method="ffmpeg_mp3_extract", outcome_code="success" if audio_path else "error")
'''

content = content.replace(
'''            try:
                if job.generate_audio and video_path:
                    audio_path = await asyncio.to_thread(
                        _extract_audio_from_reel, video_path, job.job_id
                    )''', replacement)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
