with open('backend/services/acquisition_service.py', 'r') as f:
    content = f.read()

import re

# 1. create_shadow_job_decisions needs fail-open
content = content.replace(
'''async def create_shadow_job_decisions(
    *, job_id: str, user_id: str, source_ids: Iterable[str]
) -> Dict[str, str]:
    """Create deterministic write-once decisions without changing execution."""
    db = await get_database()
    collection = db["acquisition_decisions"]
    result: Dict[str, str] = {}
    operations = list(AcquisitionOperation)

    for source_id in dict.fromkeys(source_ids):''',
'''async def create_shadow_job_decisions(
    *, job_id: str, user_id: str, source_ids: Iterable[str]
) -> Dict[str, str]:
    """Create deterministic write-once decisions without changing execution."""
    result: Dict[str, str] = {}
    try:
        db = await get_database()
        collection = db["acquisition_decisions"]
        operations = list(AcquisitionOperation)
    except Exception as e:
        print(f"[Acquisition][shadow] failed to init decision creation for {job_id}: {e}")
        return {s: _decision_id(job_id, s) for s in dict.fromkeys(source_ids)}

    for source_id in dict.fromkeys(source_ids):'''
)

content = content.replace(
'''        try:
            await collection.insert_one(payload)
        except DuplicateKeyError:
            # Write-once means an existing decision is returned, never replaced.
            pass
    return result''',
'''        try:
            await collection.insert_one(payload)
        except DuplicateKeyError:
            pass
        except Exception as e:
            print(f"[Acquisition][shadow] failed to insert decision for {source_id}: {e}")
    return result'''
)

# 2. load_job_decision_ids needs fail-open
content = content.replace(
'''async def load_job_decision_ids(job_id: str) -> Dict[str, str]:
    db = await get_database()
    cursor = db["acquisition_decisions"].find({"job_id": job_id})
    return {
        row["source_ref"]["source_id"]: row["decision_id"]
        async for row in cursor
    }''',
'''async def load_job_decision_ids(job_id: str) -> Dict[str, str]:
    try:
        db = await get_database()
        cursor = db["acquisition_decisions"].find({"job_id": job_id})
        return {
            row["source_ref"]["source_id"]: row["decision_id"]
            async for row in cursor
        }
    except Exception as e:
        print(f"[Acquisition][shadow] load_job_decision_ids failed for {job_id}: {e}")
        return {}'''
)

with open('backend/services/acquisition_service.py', 'w') as f:
    f.write(content)
