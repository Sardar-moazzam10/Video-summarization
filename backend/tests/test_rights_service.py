import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.models.rights import (
    RightsBasis,
    PublicationGateStatus,
    PlatformEvidence,
    UserClaim,
    PermissionEvidence,
    SourceRightsRecord,
)
from backend.services.rights_service import (
    normalize_youtube_license,
    generate_attribution_text,
    evaluate_source_gate,
    evaluate_publication_gate,
    build_source_reuse_report,
    union_intervals,
    ensure_rights_indexes,
    upsert_rights_record,
    get_rights_record,
)
from backend.services.transcript_service import extract_video_id


def test_normalize_youtube_license():
    assert normalize_youtube_license("creativeCommon") == RightsBasis.CC_BY
    assert normalize_youtube_license("youtube") == RightsBasis.UNKNOWN
    assert normalize_youtube_license(None) == RightsBasis.UNKNOWN
    assert normalize_youtube_license("") == RightsBasis.UNKNOWN
    assert normalize_youtube_license("youtube") != RightsBasis.CC_BY


def test_attribution_text_formatting_and_normalization():
    attr1 = generate_attribution_text("Quantum Computing Intro", "MIT OpenCourseWare", "abc123xyz89", RightsBasis.CC_BY)
    assert attr1 == '"Quantum Computing Intro" by MIT OpenCourseWare — https://www.youtube.com/watch?v=abc123xyz89 — licensed under CC BY on YouTube.'
    
    attr2 = generate_attribution_text(
        "Quantum Computing Intro",
        "MIT OpenCourseWare",
        "https://www.youtube.com/watch?v=abc123xyz89",
        RightsBasis.CC_BY,
    )
    assert attr2 == '"Quantum Computing Intro" by MIT OpenCourseWare — https://www.youtube.com/watch?v=abc123xyz89 — licensed under CC BY on YouTube.'


def test_single_source_gate_truth_table():
    cc_src = SourceRightsRecord(
        record_id="r1", user_id="u1", source_type="youtube", source_id="v_cc", source_url="https://youtube.com/watch?v=v_cc",
        rights_basis=RightsBasis.CC_BY,
        attribution_required=True,
        attribution_text="Valid attribution",
        platform_evidence=PlatformEvidence(status_license="creativeCommon", verified=True),
    )
    status, warnings = evaluate_source_gate(cc_src)
    assert status == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS
    assert len(warnings) == 1
    assert any("Recorded CC BY metadata reflects platform status" in w for w in warnings)

    std_src = SourceRightsRecord(
        record_id="r2", user_id="u1", source_type="youtube", source_id="v_std", source_url="https://youtube.com/watch?v=v_std",
        rights_basis=RightsBasis.UNKNOWN,
        platform_evidence=PlatformEvidence(status_license="youtube", verified=True),
    )
    status, warnings = evaluate_source_gate(std_src)
    assert status == PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY
    assert any("Standard YouTube License" in w for w in warnings)

    user_owned_src = SourceRightsRecord(
        record_id="r3", user_id="u1", source_type="youtube", source_id="v_usr", source_url="https://youtube.com/watch?v=v_usr",
        rights_basis=RightsBasis.USER_OWNED,
        user_claim=UserClaim(claim_type="ownership", user_id="u1"),
    )
    status, warnings = evaluate_source_gate(user_owned_src)
    assert status == PublicationGateStatus.MANUAL_REVIEW_REQUIRED
    assert any("ownership declaration" in w for w in warnings)

    perm_src = SourceRightsRecord(
        record_id="r4", user_id="u1", source_type="youtube", source_id="v_perm", source_url="https://youtube.com/watch?v=v_perm",
        rights_basis=RightsBasis.PERMISSION_GRANTED,
        permission_evidence=PermissionEvidence(grantor="Author", scope_adaptation=True, scope_publication=True),
    )
    status, warnings = evaluate_source_gate(perm_src)
    assert status == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS
    assert len(warnings) == 0

    incomp_perm = SourceRightsRecord(
        record_id="r5", user_id="u1", source_type="youtube", source_id="v_incomp", source_url="https://youtube.com/watch?v=v_incomp",
        rights_basis=RightsBasis.UNKNOWN,
        permission_evidence=PermissionEvidence(grantor="Author", scope_adaptation=True, scope_publication=False),
    )
    status, warnings = evaluate_source_gate(incomp_perm)
    assert status == PublicationGateStatus.MANUAL_REVIEW_REQUIRED

    unknown_src = SourceRightsRecord(
        record_id="r6", user_id="u1", source_type="youtube", source_id="v_unk", source_url="https://youtube.com/watch?v=v_unk",
        rights_basis=RightsBasis.UNKNOWN,
    )
    status, warnings = evaluate_source_gate(unknown_src)
    assert status == PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY


def test_evidence_coexistence():
    src = SourceRightsRecord(
        record_id="rec_coexist",
        user_id="user_123",
        source_type="youtube",
        source_id="v_coexist",
        source_url="https://youtube.com/watch?v=v_coexist",
        rights_basis=RightsBasis.PERMISSION_GRANTED,
        platform_evidence=PlatformEvidence(
            source_platform="youtube",
            status_license="youtube",
            verified=True,
        ),
        permission_evidence=PermissionEvidence(
            grantor="Original Creator",
            scope_adaptation=True,
            scope_publication=True,
            evidence_url="https://example.com/license.pdf",
        ),
    )
    status, warnings = evaluate_source_gate(src)
    assert status == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS
    assert len(warnings) == 0

    assert src.platform_evidence.status_license == "youtube"
    assert src.platform_evidence.status_license != "creativeCommon"
    assert src.permission_evidence.scope_publication is True
    assert src.rights_basis == RightsBasis.PERMISSION_GRANTED


def test_multi_source_gate_most_restrictive_wins():
    cc_src = SourceRightsRecord(
        record_id="r1", user_id="u1", source_type="youtube", source_id="v1", source_url="https://youtube.com/watch?v=v1",
        rights_basis=RightsBasis.CC_BY,
        attribution_required=True,
        attribution_text="Attribution",
        platform_evidence=PlatformEvidence(status_license="creativeCommon", verified=True),
    )
    user_src = SourceRightsRecord(
        record_id="r2", user_id="u1", source_type="youtube", source_id="v2", source_url="https://youtube.com/watch?v=v2",
        rights_basis=RightsBasis.USER_OWNED,
        user_claim=UserClaim(claim_type="ownership", user_id="u1"),
    )
    std_src = SourceRightsRecord(
        record_id="r3", user_id="u1", source_type="youtube", source_id="v3", source_url="https://youtube.com/watch?v=v3",
        rights_basis=RightsBasis.UNKNOWN,
        platform_evidence=PlatformEvidence(status_license="youtube", verified=True),
    )

    overall, _ = evaluate_publication_gate([cc_src, cc_src])
    assert overall == PublicationGateStatus.ELIGIBLE_BY_RECORDED_RIGHTS

    overall, warnings = evaluate_publication_gate([cc_src, user_src])
    assert overall == PublicationGateStatus.MANUAL_REVIEW_REQUIRED

    overall, warnings = evaluate_publication_gate([cc_src, std_src])
    assert overall == PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY

    overall, _ = evaluate_publication_gate([cc_src, user_src, std_src])
    assert overall == PublicationGateStatus.RESTRICTED_BY_PRODUCT_POLICY


def test_source_reuse_report_deterministic_fixture():
    highlight_segments = [
        {"video_id": "v1000", "start_time": 0.0, "end_time": 40.0},
        {"video_id": "v1000", "start_time": 100.0, "end_time": 160.0},
        {"video_id": "v1000", "start_time": 300.0, "end_time": 320.0},
    ]
    source_durations = {"v1000": 1000.0}

    report = build_source_reuse_report(highlight_segments, source_durations)
    assert report["total_output_seconds"] == 120.0
    assert report["source_count"] == 1

    s = report["sources"]["v1000"]
    assert s["source_media_seconds"] == 1000.0
    assert s["used_seconds"] == 120.0
    assert s["clip_count"] == 3
    assert s["max_continuous_interval_seconds"] == 60.0
    assert s["usage_ratio"] == 0.12


def test_source_reuse_report_unioned_overlapping_intervals():
    highlight_segments = [
        {"video_id": "v_overlap", "start_time": 0.0, "end_time": 40.0},
        {"video_id": "v_overlap", "start_time": 20.0, "end_time": 60.0},
        {"video_id": "v1", "start_time": 10.0, "end_time": 30.0},
        {"video_id": "v1", "start_time": 60.0, "end_time": 110.0},
    ]
    source_durations = {
        "v_overlap": 200.0,
        "v1": 200.0,
    }

    report = build_source_reuse_report(highlight_segments, source_durations)
    assert report["source_count"] == 2
    s_overlap = report["sources"]["v_overlap"]
    assert s_overlap["used_seconds"] == 60.0
    assert s_overlap["clip_count"] == 2
    assert s_overlap["max_continuous_interval_seconds"] == 40.0
    assert s_overlap["usage_ratio"] == 0.30

    s1 = report["sources"]["v1"]
    assert s1["source_media_seconds"] == 200.0
    assert s1["used_seconds"] == 70.0
    assert s1["clip_count"] == 2
    assert s1["max_continuous_interval_seconds"] == 50.0
    assert s1["usage_ratio"] == 0.35


def test_source_reuse_report_url_normalization():
    highlight_segments = [
        {"video_id": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "start_time": 10.0, "end_time": 30.0},
        {"video_id": "dQw4w9WgXcQ", "start_time": 50.0, "end_time": 70.0},
    ]
    source_durations = {"dQw4w9WgXcQ": 200.0}

    report = build_source_reuse_report(highlight_segments, source_durations)
    assert report["source_count"] == 1
    assert "dQw4w9WgXcQ" in report["sources"]
    assert report["sources"]["dQw4w9WgXcQ"]["used_seconds"] == 40.0
    assert report["sources"]["dQw4w9WgXcQ"]["clip_count"] == 2
    assert report["sources"]["dQw4w9WgXcQ"]["usage_ratio"] <= 1.0


@pytest.mark.asyncio
async def test_ensure_rights_indexes_and_idempotence():
    mock_coll = AsyncMock()
    mock_coll.create_index = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__.return_value = mock_coll

    await ensure_rights_indexes(db=mock_db)
    
    mock_coll.create_index.assert_called_once_with(
        [("user_id", 1), ("source_type", 1), ("source_id", 1)],
        unique=True,
    )


@pytest.mark.asyncio
async def test_canonical_video_id_normalization():
    bare = "dQw4w9WgXcQ"
    full_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    short_url = "https://youtu.be/dQw4w9WgXcQ"

    assert extract_video_id(bare) == "dQw4w9WgXcQ"
    assert extract_video_id(full_url) == "dQw4w9WgXcQ"
    assert extract_video_id(short_url) == "dQw4w9WgXcQ"
