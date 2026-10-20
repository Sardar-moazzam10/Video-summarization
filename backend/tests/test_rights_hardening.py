import copy
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorClient

from backend.api.merge import _media_delivery_allowed
from backend.core.config import get_settings
from backend.core.security import get_current_user, get_current_user_optional
from backend.main import app
from backend.models.rights import (
    PermissionEvidence,
    PlatformEvidence,
    RightsBasis,
    SourceRightsRecord,
    UserClaim,
)
from backend.services.rights_service import (
    build_job_rights_snapshot,
    ensure_rights_indexes,
    freeze_job_rights_snapshot,
    get_rights_record,
    upsert_rights_record,
)


class FreshJsonResponse:
    def __init__(self, payload, *, is_error=False):
        self.payload = payload
        self.is_error = is_error
        self.status_code = 500 if is_error else 200

    def json(self):
        return copy.deepcopy(self.payload)


def _source(source_id, *, platform_license=None, claim=None, permission=None):
    basis = RightsBasis.CC_BY if platform_license == "creativeCommon" else RightsBasis.UNKNOWN
    if permission:
        basis = RightsBasis.PERMISSION_GRANTED
    return SourceRightsRecord(
        record_id=f"record-{source_id}",
        user_id="user-a",
        source_id=source_id,
        source_url=f"https://www.youtube.com/watch?v={source_id}",
        source_title=f"Title {source_id}",
        owner_or_creator="Creator",
        rights_basis=basis,
        license_identifier="CC BY (YouTube)" if basis == RightsBasis.CC_BY else None,
        attribution_required=basis == RightsBasis.CC_BY,
        attribution_text=(
            f'"Title {source_id}" by Creator — https://www.youtube.com/watch?v={source_id} — licensed under CC BY on YouTube.'
            if basis == RightsBasis.CC_BY else None
        ),
        platform_evidence=(
            PlatformEvidence(status_license=platform_license, verified=True)
            if platform_license else None
        ),
        user_claim=claim,
        permission_evidence=permission,
    )


def test_live_shape_search_enrichment_survives_fresh_json_decoding():
    search_response = FreshJsonResponse({
        "items": [
            {"id": {"videoId": "cc-video"}, "snippet": {"title": "CC"}},
            {"id": {"videoId": "std-video"}, "snippet": {"title": "Standard"}},
        ]
    })
    status_response = FreshJsonResponse({
        "items": [
            {"id": "cc-video", "status": {"license": "creativeCommon"}},
            {"id": "std-video", "status": {"license": "youtube"}},
        ]
    })

    async def fake_get(_self, url, params=None):
        return status_response if url.endswith("/videos") else search_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        response = TestClient(app).get(
            "/api/v1/youtube/search?q=calculus&license=creativeCommon&include_rights=true"
        )

    assert response.status_code == 200
    cc, standard = response.json()["items"]
    assert cc["rights"]["verified_metadata"] is True
    assert cc["rights"]["youtube_license"] == "creativeCommon"
    assert standard["rights"]["verified_metadata"] is True
    assert standard["rights"]["youtube_license"] == "youtube"


def test_search_metadata_failure_is_explicitly_unverified():
    search_response = FreshJsonResponse({
        "items": [{"id": {"videoId": "unknown-video"}, "snippet": {"title": "Unknown"}}]
    })
    failed_status_response = FreshJsonResponse({"error": {}}, is_error=True)

    async def fake_get(_self, url, params=None):
        return failed_status_response if url.endswith("/videos") else search_response

    with patch("httpx.AsyncClient.get", new=fake_get):
        response = TestClient(app).get(
            "/api/v1/youtube/search?q=calculus&license=creativeCommon&include_rights=true"
        )

    rights = response.json()["items"][0]["rights"]
    assert rights["verified_metadata"] is False
    assert rights["youtube_license"] is None


def test_snapshot_freezes_evidence_at_evaluation_time():
    source = _source("cc-source", platform_license="creativeCommon")
    snapshot = build_job_rights_snapshot([source])

    source.platform_evidence.status_license = "youtube"
    source.rights_basis = RightsBasis.UNKNOWN
    source.attribution_text = None

    frozen = snapshot["sources"][0]
    assert snapshot["schema_version"] == "1.0"
    assert snapshot["policy_version"] == "rights-v1-fail-closed"
    assert frozen["evidence"]["platform"]["status_license"] == "creativeCommon"
    assert frozen["verification_status"] == "verified_metadata"
    assert frozen["attribution"]["text"]
    assert snapshot["aggregate"]["publication_gate_status"] == "eligible_by_recorded_rights"


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ([_source("a", platform_license="creativeCommon"), _source("b", platform_license="creativeCommon")], "eligible_by_recorded_rights"),
        ([_source("a", platform_license="creativeCommon"), _source("b", claim=UserClaim(claim_type="ownership", user_id="user-a"))], "manual_review_required"),
        ([_source("a", platform_license="creativeCommon"), _source("b", platform_license="youtube")], "restricted_by_product_policy"),
        ([_source("a", claim=UserClaim(claim_type="ownership", user_id="user-a")), _source("b", platform_license="youtube")], "restricted_by_product_policy"),
    ],
)
def test_snapshot_stores_most_restrictive_aggregate(sources, expected):
    assert build_job_rights_snapshot(sources)["aggregate"]["publication_gate_status"] == expected


class MemoryJobs:
    def __init__(self):
        self.job = {"job_id": "job-1", "user_id": "user-a"}

    async def find_one(self, query):
        return copy.deepcopy(self.job) if query.get("job_id") == "job-1" else None

    async def update_one(self, query, update):
        writable = not self.job.get("rights_snapshot")
        if writable:
            self.job.update(copy.deepcopy(update["$set"]))
        return SimpleNamespace(matched_count=1 if writable else 0)


@pytest.mark.asyncio
async def test_snapshot_persistence_is_write_once(monkeypatch):
    jobs = MemoryJobs()
    first_source = _source("source", platform_license="creativeCommon")
    second_source = _source("source", platform_license="youtube")
    resolver = AsyncMock(side_effect=[[first_source], [second_source]])
    monkeypatch.setattr(
        "backend.services.rights_service.ensure_source_rights_for_videos", resolver
    )

    first = await freeze_job_rights_snapshot(
        jobs_collection=jobs, job_id="job-1", user_id="user-a", video_ids=["source"]
    )
    second = await freeze_job_rights_snapshot(
        jobs_collection=jobs, job_id="job-1", user_id="user-a", video_ids=["source"]
    )

    assert first == second
    assert second["aggregate"]["publication_gate_status"] == "eligible_by_recorded_rights"
    assert resolver.await_count == 1


@pytest.mark.parametrize("status", ["manual_review_required", "restricted_by_product_policy"])
def test_direct_media_delivery_blocks_noneligible_snapshot(status, tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    job = {
        "job_id": "job-blocked",
        "video_path": str(media),
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation",
            "aggregate": {"publication_gate_status": status},
        },
    }
    with patch("backend.api.merge._get_media_job", new=AsyncMock(return_value=job)):
        response = TestClient(app).get("/api/v1/merge/job-blocked/video")
    assert response.status_code == 403


def test_legacy_reconstruction_cannot_authorize_media():
    assert _media_delivery_allowed({
        "publication_gate_status": "eligible_by_recorded_rights",
        "rights_snapshot": {
            "snapshot_origin": "reconstructed_legacy",
            "aggregate": {"publication_gate_status": "eligible_by_recorded_rights"},
        },
    }) is False


def test_direct_media_delivery_allows_frozen_eligible_snapshot(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    job = {
        "job_id": "job-eligible",
        "video_path": str(media),
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation",
            "aggregate": {"publication_gate_status": "eligible_by_recorded_rights"},
        },
    }
    with patch("backend.api.merge._get_media_job", new=AsyncMock(return_value=job)):
        response = TestClient(app).get("/api/v1/merge/job-eligible/video")
    assert response.status_code == 200
    assert response.content == b"video"


@pytest.mark.asyncio
async def test_real_mongo_rights_are_user_scoped_and_read_after_write():
    settings = get_settings()
    client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=1000)
    db_name = f"vidfusion_rights_test_{uuid.uuid4().hex}"
    try:
        try:
            await client.admin.command("ping")
        except Exception as exc:
            pytest.skip(f"isolated Mongo integration unavailable: {exc}")
        db = client[db_name]
        await ensure_rights_indexes(db)
        a = _source("shared", platform_license="creativeCommon")
        b = _source("shared", platform_license="youtube")
        b.user_id = "user-b"
        await upsert_rights_record(a, db)
        await upsert_rights_record(b, db)

        read_a = await get_rights_record("user-a", "youtube", "shared", db)
        read_b = await get_rights_record("user-b", "youtube", "shared", db)
        assert read_a.platform_evidence.status_license == "creativeCommon"
        assert read_b.platform_evidence.status_license == "youtube"

        a.user_claim = UserClaim(claim_type="ownership", user_id="user-a")
        await upsert_rights_record(a, db)
        unchanged_b = await get_rights_record("user-b", "youtube", "shared", db)
        assert unchanged_b.user_claim is None
    finally:
        await client.drop_database(db_name)
        client.close()


def test_direct_audio_delivery_blocks_noneligible_snapshot(tmp_path):
    media = tmp_path / "source.mp3"
    media.write_bytes(b"audio")
    job = {
        "job_id": "job-blocked-audio",
        "audio_path": str(media),
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation",
            "aggregate": {"publication_gate_status": "manual_review_required"},
        },
    }
    with patch("backend.api.merge._get_media_job", new=AsyncMock(return_value=job)):
        response = TestClient(app).get("/api/v1/merge/job-blocked-audio/audio")
    assert response.status_code == 403


def test_result_never_exposes_media_urls_for_noneligible_job():
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user-a", "role": "user"}
    job = {
        "job_id": "job-result-blocked",
        "user_id": "user-a",
        "status": "completed",
        "created_at": "2026-01-01T00:00:00Z",
        "video_path": "/tmp/video.mp4",
        "audio_path": "/tmp/audio.mp3",
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation",
            "aggregate": {"publication_gate_status": "restricted_by_product_policy"},
        },
    }
    try:
        with patch("backend.api.merge._get_owned_job", new=AsyncMock(return_value=job)):
            response = TestClient(app).get("/api/v1/merge/job-result-blocked/result")
        assert response.status_code == 200
        payload = response.json()
        assert payload["media_delivery_allowed"] is False
        assert payload["video_url"] is None
        assert payload["audio_url"] is None
    finally:
        app.dependency_overrides.clear()


def test_cross_user_media_access_is_denied_before_delivery(tmp_path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"video")
    job = {
        "job_id": "job-owned-by-a",
        "user_id": "user-a",
        "video_path": str(media),
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation",
            "aggregate": {"publication_gate_status": "eligible_by_recorded_rights"},
        },
    }
    collection = AsyncMock()
    collection.find_one = AsyncMock(return_value=job)
    app.dependency_overrides[get_current_user_optional] = lambda: {
        "sub": "user-b", "role": "user"
    }
    try:
        with patch("backend.api.merge.get_jobs_collection", new=AsyncMock(return_value=collection)):
            response = TestClient(app).get("/api/v1/merge/job-owned-by-a/video")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_manifest_uses_frozen_snapshot_without_current_rights_lookup():
    snapshot = build_job_rights_snapshot([
        _source("frozen-cc", platform_license="creativeCommon")
    ])
    job = {
        "job_id": "job-frozen",
        "user_id": "user-a",
        "video_ids": ["frozen-cc"],
        "highlight_segments": [],
        "source_durations": {},
        "rights_snapshot": snapshot,
    }
    jobs = AsyncMock()
    jobs.find_one = AsyncMock(return_value=job)
    database = MagicMock()
    database.__getitem__.return_value = jobs
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "user-a", "role": "user"
    }
    try:
        with patch("backend.api.rights.get_database", new=AsyncMock(return_value=database)):
            with patch(
                "backend.api.rights.ensure_source_rights_for_videos",
                new=AsyncMock(side_effect=AssertionError("mutable lookup must not run")),
            ):
                response = TestClient(app).get(
                    "/api/v1/rights/job/job-frozen/manifest"
                )
        assert response.status_code == 200
        payload = response.json()
        assert payload["snapshot_origin"] == "job_evaluation"
        assert payload["publication_gate_status"] == "eligible_by_recorded_rights"
        assert "frozen-cc" in payload["attribution_block"]
    finally:
        app.dependency_overrides.clear()

