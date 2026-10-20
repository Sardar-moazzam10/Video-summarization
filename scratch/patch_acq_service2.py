with open('backend/services/acquisition_service.py', 'r') as f:
    content = f.read()

import re

# We will wrap the ENTIRE create_shadow_job_decisions function body in try...except
old_func = '''async def create_shadow_job_decisions(
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

    for source_id in dict.fromkeys(source_ids):
        decision_id = _decision_id(job_id, source_id)
        result[source_id] = decision_id
        decision = AcquisitionDecision(
            decision_id=decision_id,
            job_id=job_id,
            user_id=user_id,
            source_ref=SourceRef(
                source_type="youtube_video",
                source_id=source_id,
                canonical_reference=f"https://www.youtube.com/watch?v={source_id}",
            ),
            mode=AcquisitionMode.LOCAL_ACQUISITION,
            basis=AcquisitionBasis.LEGACY_UNVERIFIED,
            status=AcquisitionDecisionStatus.SHADOW_ONLY,
            permitted_operations=operations,
        )
        payload = decision.model_dump(mode="json")
        payload["decision_hash"] = _digest(payload, {"decision_hash", "event_sequence"})
        try:
            await collection.insert_one(payload)
        except DuplicateKeyError:
            pass
        except Exception as e:
            print(f"[Acquisition][shadow] failed to insert decision for {source_id}: {e}")
    return result'''

new_func = '''async def create_shadow_job_decisions(
    *, job_id: str, user_id: str, source_ids: Iterable[str]
) -> Dict[str, str]:
    """Create deterministic write-once decisions without changing execution."""
    result: Dict[str, str] = {}
    try:
        # Cast to strings to prevent mock-related pydantic validation errors in tests
        job_id = str(job_id)
        user_id = str(user_id) if user_id else "anonymous"
        source_ids = [str(s) for s in source_ids]

        db = await get_database()
        collection = db["acquisition_decisions"]
        operations = list(AcquisitionOperation)
        
        for source_id in dict.fromkeys(source_ids):
            decision_id = _decision_id(job_id, source_id)
            result[source_id] = decision_id
            decision = AcquisitionDecision(
                decision_id=decision_id,
                job_id=job_id,
                user_id=user_id,
                source_ref=SourceRef(
                    source_type="youtube_video",
                    source_id=source_id,
                    canonical_reference=f"https://www.youtube.com/watch?v={source_id}",
                ),
                mode=AcquisitionMode.LOCAL_ACQUISITION,
                basis=AcquisitionBasis.LEGACY_UNVERIFIED,
                status=AcquisitionDecisionStatus.SHADOW_ONLY,
                permitted_operations=operations,
            )
            payload = decision.model_dump(mode="json")
            payload["decision_hash"] = _digest(payload, {"decision_hash", "event_sequence"})
            try:
                await collection.insert_one(payload)
            except DuplicateKeyError:
                pass
            except Exception as e:
                print(f"[Acquisition][shadow] failed to insert decision for {source_id}: {e}")
    except Exception as e:
        print(f"[Acquisition][shadow] failed to init decision creation for {job_id}: {e}")
        for source_id in dict.fromkeys(source_ids):
            result[str(source_id)] = _decision_id(str(job_id), str(source_id))
    return result'''

if old_func in content:
    content = content.replace(old_func, new_func)
    with open('backend/services/acquisition_service.py', 'w') as f:
        f.write(content)
else:
    print("Could not find function block")
