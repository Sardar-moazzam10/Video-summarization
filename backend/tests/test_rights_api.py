import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from backend.main import app
from backend.core.security import get_current_user
from backend.models.rights import RightsBasis, PublicationGateStatus, SourceRightsRecord
from backend.models.rights import (
    RightsBasis,
    PublicationGateStatus,
    SourceRightsRecord,
    PlatformEvidence,
    PermissionEvidence,
    UserClaim,
)
from backend.services.rights_service import (
    evaluate_publication_gate,
    ensure_source_rights_for_videos,
)


def test_youtube_search_license_filtering_and_enrichment():
    client = TestClient(app)
    
    mock_search_items = [
        {"id": {"videoId": "vid_cc_1"}, "snippet": {"title": "CC Video"}},
        {"id": {"videoId": "vid_std_2"}, "snippet": {"title": "Standard Video"}},
    ]
    mock_videos_items = [
        {
            "id": "vid_cc_1",
            "status": {"license": "creativeCommon"},
            "contentDetails": {"duration": "PT20M"},
        },
        {
            "id": "vid_std_2",
            "status": {"license": "youtube"},
            "contentDetails": {"duration": "PT1H"},
        },
    ]
    
    mock_search_resp = MagicMock()
    mock_search_resp.is_error = False
    mock_search_resp.json.return_value = {"items": mock_search_items}

    mock_videos_resp = MagicMock()
    mock_videos_resp.is_error = False
    mock_videos_resp.json.return_value = {"items": mock_videos_items}
    requests = []

    async def mock_get(url, params=None):
        requests.append((url, params.copy() if params else {}))
        if "search" in url:
            assert params.get("videoLicense") == "creativeCommon"
            return mock_search_resp
        elif "videos" in url:
            assert "part" in params
            assert set(params["part"].split(",")) == {"status", "contentDetails"}
            assert "vid_cc_1" in params["id"]
            return mock_videos_resp
        return mock_search_resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        response = client.get(
            "/api/v1/youtube/search?q=calculus&license=creativeCommon&include_rights=true"
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 2
        assert [url.rsplit("/", 1)[-1] for url, _ in requests] == ["search", "videos"]
        
        # Verify CC item has verified rights
        cc_item = items[0]
        assert cc_item["rights"]["youtube_license"] == "creativeCommon"
        assert cc_item["rights"]["license_identifier"] == "CC BY (YouTube)"
        assert cc_item["rights"]["verified_metadata"] is True
        assert cc_item["rights"]["attribution_required"] is True
        assert cc_item["duration_seconds"] == 1200.0

        # Verify Standard item
        std_item = items[1]
        assert std_item["rights"]["youtube_license"] == "youtube"
        assert std_item["rights"]["license_identifier"] == "YouTube Standard"
        assert std_item["rights"]["verified_metadata"] is True
        assert std_item["rights"]["attribution_required"] is False
        assert std_item["duration_seconds"] == 3600.0


def test_rights_attestation_endpoint():
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_author", "role": "user"}
def test_user_authorization_isolation():
    """
    CRITICAL INVARIANT (Point 5):
    User A must not be able to:
      - read User B's rights records;
      - read User B's job rights manifest;
      - mutate User B's records via attestations or permissions.
    """
    client = TestClient(app)

    with patch("backend.services.rights_service.upsert_rights_record", new_callable=AsyncMock):
        with patch("backend.services.rights_service.get_rights_record", new_callable=AsyncMock, return_value=None):
            resp = client.post(
                "/api/v1/rights/attest",
                json={
                    "source_id": "vid_custom",
                    "source_type": "youtube",
                    "claim_type": "ownership",
                    "notes": "Original creator work"
                }
            )
            assert resp.status_code == 200
            rec = resp.json()["record"]
            assert rec["rights_basis"] == "user_owned"
            assert rec["user_claim"]["claim_type"] == "ownership"
            assert rec["user_claim"]["notes"] == "Original creator work"
            # Platform metadata is not verified by user attestation
            assert rec["platform_evidence"] is None

    app.dependency_overrides.clear()


def test_user_authorization_isolation():
    """
    CRITICAL INVARIANT (Point 5 & 7):
    User A must not be able to:
      - read User B's rights records;
      - read User B's job rights manifest;
      - mutate User B's records via attestations or permissions.
      - Admin behavior is explicit (allowed).
      - Missing or unauthorized jobs fail with 404 without leaking existence.
    """
    client = TestClient(app)

    # 1. Job manifest authorization
    # Job belongs to User B ("user_b")
    mock_job_user_b = {
        "job_id": "job_user_b",
        "user_id": "user_b",
        "video_ids": ["vid_b"],
        "highlight_segments": [],
        "source_durations": {},
    }

    # User A ("user_a") tries to fetch User B's job manifest
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user_a", "role": "user"}
    
    jobs_coll = AsyncMock()
    jobs_coll.find_one = AsyncMock(return_value=mock_job_user_b)
    rights_coll = AsyncMock()
    rights_coll.find_one = AsyncMock(return_value=None)
    mock_db = MagicMock()
    mock_coll = AsyncMock()
    mock_coll.find_one = AsyncMock(return_value=mock_job_user_b)
    mock_db.__getitem__.return_value = mock_coll
    mock_db.__getitem__.side_effect = lambda name: jobs_coll if name == "jobs" else rights_coll

    with patch("backend.api.rights.get_database", new_callable=AsyncMock, return_value=mock_db):
        resp = client.get("/api/v1/rights/job/job_user_b/manifest")
        # Deny without leaking job existence -> 404
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Job not found"

    # 2. Source rights record isolation
    # When User A requests record for vid_b, it queries user_a's namespace only
    # Admin CAN access User B's job manifest
    app.dependency_overrides[get_current_user] = lambda: {"sub": "admin_user", "role": "admin"}
    with patch("backend.api.rights.get_database", new_callable=AsyncMock, return_value=mock_db):
        with patch("backend.api.rights.ensure_source_rights_for_videos", new_callable=AsyncMock, return_value=[]):
            resp_admin = client.get("/api/v1/rights/job/job_user_b/manifest")
            assert resp_admin.status_code == 200

    # 2. Source rights record lookup isolation
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user_a", "role": "user"}
    with patch("backend.api.rights.get_rights_record", new_callable=AsyncMock) as mock_get_rec:
        mock_get_rec.return_value = None  # No record under user_a
        resp = client.get("/api/v1/rights/vid_b")
        assert resp.status_code == 200
        assert resp.json()["recorded"] is False
        # Verifies the lookup was scoped to user_a, not user_b
        mock_get_rec.assert_called_once_with("user_a", "youtube", "vid_b")

    # 3. Attestation and Permission write isolation: User A writes cannot mutate User B
    with patch("backend.api.rights.record_user_attestation", new_callable=AsyncMock) as mock_attest:
        mock_attest.return_value = SourceRightsRecord(
            record_id="rec_a",
            user_id="user_a",
            source_type="youtube",
            source_id="vid_b",
            source_url="https://www.youtube.com/watch?v=vid_b",
            rights_basis=RightsBasis.USER_OWNED,
        )
        resp = client.post(
            "/api/v1/rights/attest",
            json={"source_id": "vid_b", "source_type": "youtube", "claim_type": "ownership"}
        )
        assert resp.status_code == 200
        # Authoritatively scopes mutation to user_a
        assert mock_attest.call_args[1]["user_id"] == "user_a"

    with patch("backend.api.rights.record_permission", new_callable=AsyncMock) as mock_perm:
        mock_perm.return_value = SourceRightsRecord(
            record_id="rec_a_perm",
            user_id="user_a",
            source_type="youtube",
            source_id="vid_b",
            source_url="https://www.youtube.com/watch?v=vid_b",
            rights_basis=RightsBasis.PERMISSION_GRANTED,
        )
        resp = client.post(
            "/api/v1/rights/permission",
            json={
                "source_id": "vid_b",
                "source_type": "youtube",
                "grantor": "Licensor",
                "scope_adaptation": True,
                "scope_publication": True
            }
        )
        assert resp.status_code == 200
        # Authoritatively scopes permission to user_a
        assert mock_perm.call_args[1]["user_id"] == "user_a"

    app.dependency_overrides.clear()


def test_multi_source_publication_policy_cases():
    """
    Point 7: Integration testing of Multi-Source Policy Cases A - E
    """
    # Source fixtures
    cc_src = SourceRightsRecord(
        record_id="r1", user_id="u", source_type="youtube", source_id="v1", source_url="https://youtube.com/watch?v=v1",
        rights_basis=RightsBasis.CC_BY,
        attribution_required=True,
        attribution_text='"V1" by Channel — https://youtube.com/watch?v=v1 — licensed under CC BY on YouTube.',
        platform_evidence=PlatformEvidence(status_license="creativeCommon", verified=True),
    )
    cc_src_2 = SourceRightsRecord(
        record_id="r2", user_id="u", source_type="youtube", source_id="v2", source_url="https://youtube.com/watch?v=v2",
        rights_basis=RightsBasis.CC_BY,
        attribution_required=True,
        attribution_text='"V2" by Channel — https://youtube.com/watch?v=v2 — licensed under CC BY on YouTube.',
        platform_evidence=PlatformEvidence(status_license="creativeCommon", verified=True),
    )
    std_src = SourceRightsRecord(
        record_id="r3", user_id="u", source_type="youtube", source_id="v3", source_url="https://youtube.com/watch?v=v3",
        rights_basis=RightsBasis.UNKNOWN,
        platform_evidence=PlatformEvidence(status_license="youtube", verified=True),
    )
    perm_src = SourceRightsRecord(
        record_id="r4", user_id="u", source_type="youtube", source_id="v4", source_url="https://youtube.com/watch?v=v4",
        rights_basis=RightsBasis.PERMISSION_GRANTED,
        permission_evidence=PermissionEvidence(grantor="Author", scope_adaptation=True, scope_publication=True),
    )
    unknown_src = SourceRightsRecord(
        record_id="r5", user_id="u", source_type="youtube", source_id="v5", source_url="https://youtube.com/watch?v=v5",
        rights_basis=RightsBasis.UNKNOWN,
    )
    fair_use_src = SourceRightsRecord(
        record_id="r6", user_id="u", source_type="youtube", source_id="v6", source_url="https://youtube.com/watch?v=v6",
        rights_basis=RightsBasis.COPYRIGHT_EXCEPTION,
        user_claim=UserClaim(claim_type="fair_use", user_id="u"),
    )

    # Case A: CC BY + CC BY -> eligible_by_recorded_rights
    gate, warnings = evaluate_publication_gate([cc_src, cc_src_2])
    assert gate == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS

    # Case B: CC BY + Standard YouTube License -> restricted_by_product_policy
    gate, warnings = evaluate_publication_gate([cc_src, std_src])
    assert gate == PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY

    # Case C: CC BY + valid permission-granted source -> eligible_by_recorded_rights
    gate, warnings = evaluate_publication_gate([cc_src, perm_src])
    assert gate == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS

    # Case D: One unknown source -> restricted_by_product_policy
    gate, warnings = evaluate_publication_gate([cc_src, unknown_src])
    assert gate == PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY

    # Case E: Copyright exception source -> manual_review_required
    gate, warnings = evaluate_publication_gate([cc_src, fair_use_src])
    assert gate == PublicationGateStatus.MANUAL_REVIEW_REQUIRED


@pytest.mark.asyncio
async def test_search_to_job_rights_handoff_and_authoritative_resolution():
    """
    CRITICAL INVARIANT (Point 2):
    Prove that when a user selects a video, the server authoritatively fetches
    and persists verified status.license so CC BY does NOT silently degrade to UNKNOWN.
    """
    mock_video_resp = MagicMock()
    mock_video_resp.is_error = False
    mock_video_resp.json.return_value = {
        "items": [
            {
                "id": "dQw4w9WgXcQ",
                "status": {"license": "creativeCommon"},
                "snippet": {"title": "Rick Roll CC Edition", "channelTitle": "Rick Astley"},
            }
        ]
    }

    mock_db = MagicMock()
    mock_coll = AsyncMock()
    # No pre-existing record in DB
    mock_coll.find_one = AsyncMock(return_value=None)
    mock_coll.update_one = AsyncMock()
    mock_db.__getitem__.return_value = mock_coll

    with patch("httpx.AsyncClient.get", return_value=mock_video_resp):
        with patch("backend.services.rights_service.get_database", new_callable=AsyncMock, return_value=mock_db):
            records = await ensure_source_rights_for_videos(
                user_id="test_user",
                video_ids=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
                db=mock_db,
            )
            assert len(records) == 1
            rec = records[0]
            assert rec.source_id == "dQw4w9WgXcQ"
            assert rec.rights_basis == RightsBasis.CC_BY
            assert rec.platform_evidence is not None
            assert rec.platform_evidence.verified is True
            assert rec.platform_evidence.status_license == "creativeCommon"
            assert rec.attribution_required is True
            # Verifies that MongoDB was updated to persist the verified metadata
            assert mock_coll.update_one.called


def test_standard_license_generated_note_export_remains_available():
    app.dependency_overrides[get_current_user] = lambda: {"sub": "user_123", "role": "user"}
    client = TestClient(app)

    mock_job_data = {
        "job_id": "test_study_job",
        "user_id": "user_123",
        "status": "completed",
        "summary_text": "Executive summary for study purposes.",
        "rich_output": None,
        "publication_gate_status": "restricted_by_product_policy",
        "rights_snapshot": {
            "snapshot_origin": "job_evaluation",
            "sources": [{
                "source_id": "standard",
                "verification_status": "verified_metadata",
                "publication_gate_status": "restricted_by_product_policy",
                "evidence": {"platform": {"verified": True, "status_license": "youtube"}},
            }],
            "aggregate": {"publication_gate_status": "restricted_by_product_policy"},
        },
    }

    with patch("backend.api.merge._get_owned_job", new_callable=AsyncMock, return_value=mock_job_data):
        response = client.get("/api/v1/merge/test_study_job/export?format=text")
        assert response.status_code == 200
        assert b"Executive summary for study purposes." in response.content

    app.dependency_overrides.clear()
