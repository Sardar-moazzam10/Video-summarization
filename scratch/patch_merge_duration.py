with open('backend/api/merge.py', 'r') as f:
    content = f.read()
import uuid

import_stmt = "from ..services.acquisition_service import create_shadow_job_decisions, set_observation_context, reset_observation_context, finalize_shadow_manifest, append_event, load_job_decision_ids"

replacement = '''
    import uuid
    job_id = str(uuid.uuid4())
    dec_ids = await create_shadow_job_decisions(
        job_id=job_id,
        user_id=current_user.get("sub", "anonymous"),
        source_ids=clean_ids,
    )
    acq_token = set_observation_context(
        job_id=job_id, user_id=current_user.get("sub", "anonymous"), decision_ids=dec_ids
    )
    try:
        for vid in clean_ids:
            await append_event(source_id=vid, operation="metadata_read", phase="attempted", method="duration_probe", outcome_code="started")
        resolved = await asyncio.to_thread(get_durations, clean_ids)
        for vid in clean_ids:
            d = resolved.get(vid)
            await append_event(source_id=vid, operation="metadata_read", phase="succeeded" if d is not None else "failed", method="duration_probe", outcome_code="success" if d is not None else "not_found")
    finally:
        reset_observation_context(acq_token)
'''

content = content.replace(
    'resolved = await asyncio.to_thread(get_durations, clean_ids)',
    replacement
)

content = content.replace(
    'job = MergeJob(',
    'job = MergeJob(\\n        job_id=job_id,'
)

with open('backend/api/merge.py', 'w') as f:
    f.write(content)
