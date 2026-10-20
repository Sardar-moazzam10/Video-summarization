with open('backend/api/merge.py', 'r') as f:
    content = f.read()

content = content.replace(
'''    except asyncio.CancelledError:
        pass''',
'''    except asyncio.CancelledError:
        if job.status not in (JobStatus.COMPLETED, JobStatus.PARTIAL_SUCCESS, JobStatus.VIDEO_READY):
            job.status = JobStatus.FAILED
            job.error_message = "Job was cancelled"
            try:
                loop = asyncio.get_running_loop()
                if not loop.is_closed():
                    await jobs_collection.update_one(
                        {"job_id": job_id},
                        {"$set": {
                            "status": job.status,
                            "error_message": job.error_message
                        }}
                    )
            except BaseException:
                pass
        raise'''
)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
