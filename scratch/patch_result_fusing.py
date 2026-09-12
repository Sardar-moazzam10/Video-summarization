with open('/home/weiblocks/Desktop/Video-summarization/backend/api/merge.py', 'r') as f:
    content = f.read()

old_code = """    video_ready_statuses = {
        JobStatus.VIDEO_READY.value,
        JobStatus.SUMMARIZING.value,
        JobStatus.ENRICHING.value,
        JobStatus.GENERATING_VOICE.value,
    }"""

new_code = """    video_ready_statuses = {
        JobStatus.VIDEO_READY.value,
        JobStatus.FUSING.value,
        JobStatus.SUMMARIZING.value,
        JobStatus.ENRICHING.value,
        JobStatus.GENERATING_VOICE.value,
    }"""

content = content.replace(old_code, new_code)
with open('/home/weiblocks/Desktop/Video-summarization/backend/api/merge.py', 'w') as f:
    f.write(content)
print("Patched get_job_result with FUSING")
