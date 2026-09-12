with open('/home/weiblocks/Desktop/Video-summarization/backend/api/merge.py', 'r') as f:
    content = f.read()

old_code = """    allowed_statuses = {
        JobStatus.COMPLETED.value,
        JobStatus.PARTIAL_SUCCESS.value,
        JobStatus.VIDEO_READY.value,
    }
    if job_data["status"] not in allowed_statuses:
        raise HTTPException(
            400,
            f"Job not completed. Current status: {job_data['status']}"
        )

    summary_pending = job_data["status"] == JobStatus.VIDEO_READY.value"""

new_code = """    video_ready_statuses = {
        JobStatus.VIDEO_READY.value,
        JobStatus.SUMMARIZING.value,
        JobStatus.ENRICHING.value,
        JobStatus.GENERATING_VOICE.value,
    }
    
    allowed_statuses = {
        JobStatus.COMPLETED.value,
        JobStatus.PARTIAL_SUCCESS.value,
    } | video_ready_statuses
    
    if job_data["status"] not in allowed_statuses:
        raise HTTPException(
            400,
            f"Job not completed. Current status: {job_data['status']}"
        )

    summary_pending = job_data["status"] in video_ready_statuses"""

content = content.replace(old_code, new_code)

with open('/home/weiblocks/Desktop/Video-summarization/backend/api/merge.py', 'w') as f:
    f.write(content)
print("Patched get_job_result")
