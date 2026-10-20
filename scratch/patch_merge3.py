with open('backend/api/merge.py', 'r') as f:
    content = f.read()

content = content.replace(
'''    finally:
        if acq_token is not None:
            try:
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
            task = asyncio.current_task()
            if not (task and task.cancelled()):
                await asyncio.sleep(300)  # Keep in memory for 5 minutes
        except BaseException:
            pass
        _active_jobs.pop(job_id, None)''',
'''    except asyncio.CancelledError:
        pass
    finally:
        if acq_token is not None:
            try:
                loop = asyncio.get_running_loop()
                if not loop.is_closed():
                    await finalize_shadow_manifest(
                        job_id,
                        reason="job_completed" if job.status in (JobStatus.COMPLETED, JobStatus.PARTIAL_SUCCESS, JobStatus.VIDEO_READY) else "job_failed"
                    )
            except BaseException:
                pass
            reset_observation_context(acq_token)
        # Clean up memory after some time
        try:
            loop = asyncio.get_running_loop()
            if not loop.is_closed():
                await asyncio.sleep(300)  # Keep in memory for 5 minutes
        except BaseException:
            pass
        _active_jobs.pop(job_id, None)'''
)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
