"""Append-only, non-authoritative acquisition observability for ACQ-M1A."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from ..core.database import get_database
from ..models.acquisition import (
    AcquisitionArtifact,
    AcquisitionBasis,
    AcquisitionDecision,
    AcquisitionDecisionStatus,
    AcquisitionEvent,
    AcquisitionMode,
    AcquisitionOperation,
    FinalAcquisitionManifest,
    SourceRef,
)


SCHEMA_VERSION = "1.0"
POLICY_VERSION = "acquisition-v1a-shadow"


def _json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)


def _digest(payload: dict, excluded: Iterable[str] = ()) -> str:
    clean = {key: value for key, value in payload.items() if key not in set(excluded)}
    encoded = json.dumps(
        clean, sort_keys=True, separators=(",", ":"), default=_json_default
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AcquisitionObservationContext(dict):
    """Correlation only; it grants no permission and is safe to propagate to threads."""


_context: ContextVar[Optional[AcquisitionObservationContext]] = ContextVar(
    "acquisition_observation_context", default=None
)
_event_locks: Dict[str, asyncio.Lock] = {}


def set_observation_context(
    *, job_id: str, user_id: str, decision_ids: Dict[str, str]
) -> Token:
    return _context.set(AcquisitionObservationContext(
        job_id=job_id, user_id=user_id, decision_ids=dict(decision_ids)
    ))


def reset_observation_context(token: Token) -> None:
    _context.reset(token)


def current_observation_context() -> Optional[AcquisitionObservationContext]:
    return _context.get()


def _decision_id(job_id: str, source_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vidfusion:acquisition:{job_id}:{source_id}"))


async def ensure_acquisition_indexes() -> None:
    db = await get_database()
    await db["acquisition_decisions"].create_index("decision_id", unique=True)
    await db["acquisition_decisions"].create_index(
        [("job_id", ASCENDING), ("source_ref.source_id", ASCENDING)], unique=True
    )
    await db["acquisition_events"].create_index(
        [("decision_id", ASCENDING), ("sequence", ASCENDING)], unique=True
    )
    await db["acquisition_events"].create_index("event_id", unique=True)
    await db["acquisition_manifests"].create_index("job_id", unique=True)


async def create_shadow_job_decisions(
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
    return result


async def load_job_decision_ids(job_id: str) -> Dict[str, str]:
    try:
        db = await get_database()
        cursor = db["acquisition_decisions"].find({"job_id": job_id})
        return {
            row["source_ref"]["source_id"]: row["decision_id"]
            async for row in cursor
        }
    except Exception as e:
        print(f"[Acquisition][shadow] load_job_decision_ids failed for {job_id}: {e}")
        return {}


async def append_event(
    *,
    source_id: str,
    operation: AcquisitionOperation | str,
    phase: str,
    method: str,
    outcome_code: str,
    provider: Optional[str] = None,
    cache_result: str = "not_applicable",
    storage_class: str = "none",
    artifact_ref: Optional[str] = None,
    fallback_from_event_id: Optional[str] = None,
    reason_code: Optional[str] = None,
    safe_details: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Append one event. Failures are swallowed so shadow mode cannot affect jobs."""
    context = current_observation_context()
    if not context:
        return None
    decision_id = context["decision_ids"].get(source_id)
    if not decision_id:
        return None

    try:
        db = await get_database()
        decisions = db["acquisition_decisions"]
        events = db["acquisition_events"]
        lock = _event_locks.setdefault(decision_id, asyncio.Lock())
        async with lock:
            decision = await decisions.find_one_and_update(
                {"decision_id": decision_id, "evaluation_mode": "shadow"},
                {"$inc": {"event_sequence": 1}},
                return_document=True,
            )
            if not decision:
                return None
            sequence = int(decision["event_sequence"])
            previous = await events.find_one(
                {"decision_id": decision_id, "sequence": sequence - 1}
            ) if sequence > 1 else None
            event = AcquisitionEvent(
                event_id=str(uuid.uuid4()),
                sequence=sequence,
                decision_id=decision_id,
                job_id=context["job_id"],
                user_id=context["user_id"],
                source_id=source_id,
                operation=operation,
                phase=phase,
                method=method,
                provider=provider,
                outcome_code=outcome_code,
                cache_result=cache_result,
                storage_class=storage_class,
                artifact_ref=artifact_ref,
                fallback_from_event_id=fallback_from_event_id,
                reason_code=reason_code,
                safe_details={str(k): str(v) for k, v in (safe_details or {}).items()},
                previous_event_hash=previous.get("event_hash") if previous else None,
            )
            payload = event.model_dump(mode="json")
            payload["event_hash"] = _digest(payload, {"event_hash"})
            await events.insert_one(payload)
            return event.event_id
    except Exception as exc:
        print(f"[Acquisition][shadow] event append failed: {exc}")
        return None


async def finalize_shadow_manifest(job_id: str, reason: str) -> Optional[dict]:
    """Freeze one job-level shadow manifest. Existing manifests are untouched."""
    try:
        db = await get_database()
        decisions = [row async for row in db["acquisition_decisions"].find(
            {"job_id": job_id}
        )]
        if not decisions:
            return None
        events = [row async for row in db["acquisition_events"].find(
            {"job_id": job_id}
        ).sort([("decision_id", ASCENDING), ("sequence", ASCENDING)])]

        attempted = sorted({e["operation"] for e in events if e["phase"] == "attempted"})
        successful = sorted({e["operation"] for e in events if e["phase"] == "succeeded"})
        artifacts = [AcquisitionArtifact(
            artifact_ref=e["artifact_ref"],
            source_id=e["source_id"],
            storage_class=e["storage_class"],
            operation=e["operation"],
        ) for e in events if e.get("artifact_ref")]
        sequence_end: Dict[str, int] = {}
        chain_hashes: Dict[str, Optional[str]] = {}
        for event in events:
            sequence_end[event["decision_id"]] = event["sequence"]
            chain_hashes[event["decision_id"]] = event.get("event_hash")

        normalized_reason = reason if reason in {
            "job_completed", "job_failed", "job_cancelled"
        } else "job_failed"
        manifest = FinalAcquisitionManifest(
            manifest_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"vidfusion:manifest:{job_id}")),
            job_id=job_id,
            decision_ids=[d["decision_id"] for d in decisions],
            decision_hashes=[d["decision_hash"] for d in decisions],
            event_sequence_end=sequence_end,
            event_chain_hashes=chain_hashes,
            permitted_operations=sorted({
                op for d in decisions for op in d.get("permitted_operations", [])
            }),
            attempted_operations=attempted,
            successful_operations=successful,
            selected_methods=sorted({e["method"] for e in events}),
            fallback_chain=[e["method"] for e in events if e.get("fallback_from_event_id")],
            artifacts=artifacts,
            violations=[],
            retention_classes=sorted({d["retention_class"] for d in decisions}),
            cache_scopes=sorted({d["cache_scope"] for d in decisions}),
            finalization_reason=normalized_reason,
        )
        payload = manifest.model_dump(mode="json")
        payload["manifest_hash"] = _digest(payload, {"manifest_hash"})
        try:
            await db["acquisition_manifests"].insert_one(payload)
        except DuplicateKeyError:
            return await db["acquisition_manifests"].find_one(
                {"job_id": job_id}, {"_id": 0}
            )
        return payload
    except Exception as exc:
        print(f"[Acquisition][shadow] manifest finalization failed: {exc}")
        return None

