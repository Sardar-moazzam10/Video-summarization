import copy
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.merge import _media_capabilities
from backend.core.security import create_media_token, get_current_user, get_current_user_optional, verify_media_token
from backend.main import app


def _source(source_id, license_name):
    eligible = license_name == "creativeCommon"
    return {
        "source_id": source_id,
        "verification_status": "verified_metadata",
        "publication_gate_status": "eligible_by_recorded_rights" if eligible else "restricted_by_product_policy",
        "evidence": {"platform": {"verified": True, "status_license": license_name}},
        "attribution": {"required": eligible, "text": f"Attribution for {source_id}" if eligible else None},
    }


def _job(sources, aggregate, tmp_path=None):
    job = {
        "job_id": "tiered-job", "user_id": "user-a", "status": "completed",
        "created_at": "2026-01-01T00:00:00Z",
        "publication_gate_status": aggregate,
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation", "sources": copy.deepcopy(sources),
            "aggregate": {"publication_gate_status": aggregate, "warnings": [], "source_count": len(sources)},
        },
    }
    if tmp_path:
        video, audio = tmp_path / "preview.mp4", tmp_path / "preview.mp3"
        video.write_bytes(b"video")
        audio.write_bytes(b"audio")
        job.update(video_path=str(video), audio_path=str(audio))
    return job


def _result(job):
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user-a", "role": "user"}
    try:
        with patch("backend.api.merge._get_owned_job", new=AsyncMock(return_value=job)):
            response = TestClient(app).get("/api/v1/merge/tiered-job/result")
        assert response.status_code == 200
        return response.json()
    finally:
        app.dependency_overrides.clear()


def test_standard_license_returns_preview_but_not_download_or_export(tmp_path):
    payload = _result(_job([_source("standard", "youtube")], "restricted_by_product_policy", tmp_path))
    assert payload["generated_summary_visible"] is True
    assert payload["copy_summary_allowed"] is True
    assert payload["txt_export_allowed"] is True
    assert payload["pdf_export_allowed"] is True
    assert payload["preview_allowed"] is True
    assert payload["download_allowed"] is False
    assert payload["public_export_allowed"] is False
    assert "access=preview" in payload["video_url"]
    assert "access=preview" in payload["audio_url"]
    assert payload["video_download_url"] is None
    assert payload["audio_download_url"] is None
    assert payload["publication_gate_status"] == "restricted_by_product_policy"


def test_cc_by_keeps_preview_download_and_export(tmp_path):
    payload = _result(_job([_source("cc", "creativeCommon")], "eligible_by_recorded_rights", tmp_path))
    assert payload["preview_allowed"] is True
    assert payload["download_allowed"] is True
    assert payload["public_export_allowed"] is True
    assert "access=preview" in payload["video_url"]
    assert "access=download" in payload["video_download_url"]


def test_mixed_cc_and_standard_is_preview_only(tmp_path):
    job = _job([_source("cc", "creativeCommon"), _source("standard", "youtube")], "restricted_by_product_policy", tmp_path)
    capabilities = _media_capabilities(job)
    assert capabilities["preview_allowed"] is True
    assert capabilities["copy_summary_allowed"] is True
    assert capabilities["download_allowed"] is False


def test_unknown_and_manual_review_remain_fail_closed():
    unknown = _source("unknown", None)
    unknown["verification_status"] = "unverified"
    for aggregate in ("restricted_by_product_policy", "manual_review_required"):
        assert _media_capabilities(_job([unknown], aggregate)) == {
            "generated_summary_visible": False,
            "copy_summary_allowed": False,
            "txt_export_allowed": False,
            "pdf_export_allowed": False,
            "preview_allowed": False, "download_allowed": False, "public_export_allowed": False,
        }


def test_preview_token_is_scoped_and_cannot_download(tmp_path):
    job = _job([_source("standard", "youtube")], "restricted_by_product_policy", tmp_path)
    token = create_media_token("tiered-job", "video_preview", "user-a")
    assert verify_media_token(token, "tiered-job", "video_preview") is True
    assert verify_media_token(token, "tiered-job", "video_download") is False
    collection = AsyncMock()
    collection.find_one = AsyncMock(return_value=job)
    app.dependency_overrides[get_current_user_optional] = lambda: None
    try:
        with patch("backend.api.merge.get_jobs_collection", new=AsyncMock(return_value=collection)):
            response = TestClient(app).get(f"/api/v1/merge/tiered-job/video?access=download&token={token}")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_standard_owner_can_preview_but_download_and_export_are_blocked(tmp_path):
    job = _job([_source("standard", "youtube")], "restricted_by_product_policy", tmp_path)
    app.dependency_overrides[get_current_user_optional] = lambda: {"sub": "user-a", "role": "user"}
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user-a", "role": "user"}
    try:
        with patch("backend.api.merge._get_media_job", new=AsyncMock(return_value=job)), patch("backend.api.merge.append_event", new=AsyncMock()), patch("backend.api.merge.load_job_decision_ids", new=AsyncMock(return_value=[])):
            preview = TestClient(app).get("/api/v1/merge/tiered-job/video?access=preview")
            download = TestClient(app).get("/api/v1/merge/tiered-job/video?access=download")
        with patch("backend.api.merge._get_owned_job", new=AsyncMock(return_value=job)):
            txt_export = TestClient(app).get("/api/v1/merge/tiered-job/export?format=text")
            pdf_export = TestClient(app).get("/api/v1/merge/tiered-job/export?format=pdf")
        assert preview.status_code == 200
        assert preview.headers.get("content-disposition") is None
        assert download.status_code == 403
        assert txt_export.status_code == 200
        assert pdf_export.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_reconstructed_snapshot_never_gets_preview():
    job = _job([_source("standard", "youtube")], "restricted_by_product_policy")
    job["rights_snapshot"]["snapshot_origin"] = "reconstructed_legacy"
    assert _media_capabilities(job)["preview_allowed"] is False
