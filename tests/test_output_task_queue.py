from datetime import datetime, timedelta

import pytest

from backend.services.output_task_queue import (
    activate_output_tasks,
    claim_output_task,
    enqueue_output_task,
    finish_output_task,
    maintain_output_task_lease,
    reconcile_job_output_status,
    recover_prepared_output_dispatches,
)
import asyncio


class Result:
    modified_count = 1


class Collection:
    def __init__(self):
        self.docs = []

    async def update_one(self, query, update, upsert=False):
        doc = next((item for item in self.docs if all(item.get(k) == v for k, v in query.items())), None)
        if doc is None and upsert:
            doc = dict(update.get("$setOnInsert", {}))
            self.docs.append(doc)
        elif doc is not None:
            doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                doc.pop(key, None)
        return Result()

    def find(self, query):
        docs = [
            item for item in self.docs
            if all(item.get(k) == v for k, v in query.items())
        ]

        class Cursor:
            def __init__(self, values):
                self._values = iter(values)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._values)
                except StopIteration:
                    raise StopAsyncIteration

        return Cursor(docs)

    async def count_documents(self, query):
        return sum(
            1 for item in self.docs
            if all(item.get(k) == v for k, v in query.items())
        )

    async def find_one(self, query):
        return next((item for item in self.docs if all(item.get(k) == v for k, v in query.items())), None)

    async def find_one_and_update(self, query, update, **kwargs):
        now = datetime.utcnow()
        candidates = [item for item in self.docs if item["output_type"] == query["output_type"]]
        candidates = [item for item in candidates if item["attempts"] < 3 and (
            item["status"] == "queued" or
            (item["status"] == "running" and item["lease_expires_at"] <= now)
        )]
        if not candidates:
            return None
        doc = candidates[0]
        doc.update(update["$set"])
        doc["attempts"] += update["$inc"]["attempts"]
        return dict(doc)

    async def update_many(self, query, update):
        modified = 0
        for doc in self.docs:
            if all(doc.get(key) == value for key, value in query.items()):
                doc.update(update.get("$set", {}))
                modified += 1
        result = Result()
        result.modified_count = modified
        return result


class Database(dict):
    def __missing__(self, key):
        self[key] = Collection()
        return self[key]


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_and_claim_has_a_lease():
    database = Database()
    first = await enqueue_output_task(
        database, job_id="j", manifest_version=1, output_type="text",
    )
    second = await enqueue_output_task(
        database, job_id="j", manifest_version=1, output_type="text",
    )
    assert first["task_id"] == second["task_id"]
    assert len(database["output_tasks"].docs) == 1

    claimed = await claim_output_task(database, output_type="text", worker_id="worker")
    assert claimed["status"] == "running"
    assert claimed["lease_owner"] == "worker"
    assert claimed["lease_expires_at"] > datetime.utcnow()


@pytest.mark.asyncio
async def test_failure_requeues_until_attempt_limit():
    database = Database()
    await enqueue_output_task(database, job_id="j", manifest_version=1, output_type="text")
    for attempt in range(3):
        claimed = await claim_output_task(database, output_type="text", worker_id="worker")
        assert claimed is not None
        await finish_output_task(
            database, task_id=claimed["task_id"], worker_id="worker",
            succeeded=False, error="boom",
        )
        expected = "queued" if attempt < 2 else "failed"
        assert database["output_tasks"].docs[0]["status"] == expected


@pytest.mark.asyncio
async def test_active_worker_renews_lease_until_stopped(monkeypatch):
    calls = []

    async def heartbeat(database, task_id, worker_id, lease_seconds):
        calls.append((task_id, worker_id, lease_seconds))
        return True

    monkeypatch.setattr(
        "backend.services.output_task_queue.heartbeat_output_task", heartbeat
    )
    stop = asyncio.Event()
    lease = asyncio.create_task(maintain_output_task_lease(
        {}, task_id="task", worker_id="worker", stop_event=stop,
        lease_seconds=0.15,
    ))
    await asyncio.sleep(0.13)
    stop.set()
    assert await lease is True
    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_sibling_tasks_are_unclaimable_until_released_together():
    database = Database()
    for output_type in ("video", "text"):
        await enqueue_output_task(
            database,
            job_id="j",
            manifest_version=1,
            output_type=output_type,
            initial_status="held",
        )
    assert await claim_output_task(
        database, output_type="video", worker_id="worker"
    ) is None
    assert await activate_output_tasks(
        database, job_id="j", manifest_version=1
    ) == 2
    assert await claim_output_task(
        database, output_type="video", worker_id="worker"
    ) is not None


@pytest.mark.asyncio
async def test_restart_releases_complete_prepared_sibling_dispatch():
    database = Database()
    database["jobs"].docs.append({
        "job_id": "j",
        "output_execution_mode": "durable_workers",
        "output_dispatch_state": "prepared",
        "output_manifest_version": 1,
        "output_expected_tasks": 2,
    })
    for output_type in ("video", "text"):
        await enqueue_output_task(
            database, job_id="j", manifest_version=1,
            output_type=output_type, initial_status="held",
        )

    assert await recover_prepared_output_dispatches(database) == {
        "activated": 1, "rejected": 0,
    }
    assert {task["status"] for task in database["output_tasks"].docs} == {"queued"}
    assert database["jobs"].docs[0]["output_dispatch_state"] == "active"


@pytest.mark.asyncio
async def test_restart_rejects_incomplete_prepared_dispatch_for_orphan_recovery():
    database = Database()
    database["jobs"].docs.append({
        "job_id": "j",
        "output_execution_mode": "durable_workers",
        "output_dispatch_state": "prepared",
        "output_manifest_version": 1,
        "output_expected_tasks": 2,
    })
    await enqueue_output_task(
        database, job_id="j", manifest_version=1,
        output_type="video", initial_status="held",
    )

    assert await recover_prepared_output_dispatches(database) == {
        "activated": 0, "rejected": 1,
    }
    assert database["output_tasks"].docs[0]["status"] == "cancelled"
    assert "output_execution_mode" not in database["jobs"].docs[0]


@pytest.mark.asyncio
async def test_reconciliation_closes_completion_race_after_both_publish():
    database = Database()
    database["jobs"].docs.append({
        "job_id": "j",
        "generate_video": True,
        "status": "generating_video",
        "video_component": {"status": "ready"},
        "text_component": {"status": "ready"},
    })
    assert await reconcile_job_output_status(database, "j") == "completed"
    job = database["jobs"].docs[0]
    assert job["status"] == "completed"
    assert job["progress_percent"] == 100


@pytest.mark.asyncio
async def test_reconciliation_reports_partial_success_when_one_branch_fails():
    database = Database()
    database["jobs"].docs.append({
        "job_id": "j",
        "generate_video": True,
        "video_component": {"status": "failed"},
        "text_component": {"status": "ready"},
    })
    assert await reconcile_job_output_status(database, "j") == "partial_success"
