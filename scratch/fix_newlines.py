with open('backend/api/merge.py', 'r') as f:
    content = f.read()

content = content.replace("job = MergeJob(\\\\n        job_id=job_id,", "job = MergeJob(\\n        job_id=job_id,")

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
