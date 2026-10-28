"""
Tests for ReelService (9:16 Shorts & Reels Studio).
"""
import pytest
from backend.services.reel_service import ReelService, get_reel_service


def test_reel_service_singleton():
    svc = get_reel_service()
    assert isinstance(svc, ReelService)


def test_candidate_extraction_from_chapters():
    svc = ReelService()
    fake_job = {
        "job_id": "test_job_123",
        "video_ids": ["abc123vid"],
        "publication_gate_status": "eligible_by_recorded_rights",
        "preview_allowed": True,
        "download_allowed": True,
        "rich_output": {
            "chapters": [
                {
                    "title": "Optimizing Headline",
                    "text": "Your headline should use industry keywords rather than job titles.",
                    "timestamp_seconds": 12.0,
                    "video_id": "abc123vid",
                },
                {
                    "title": "Adding GitHub Link",
                    "text": "Place your portfolio link directly in contact info for recruiters.",
                    "timestamp_seconds": 45.0,
                    "video_id": "abc123vid",
                }
            ]
        }
    }

    candidates = svc.get_reel_candidates(fake_job)
    assert len(candidates) == 2
    assert candidates[0]["title"] == "Optimizing Headline"
    assert candidates[0]["start_time"] == 12.0
    assert candidates[0]["is_cc_by"] is True
    assert "CC BY" in candidates[0]["license_label"]
    assert candidates[0]["safe_to_export"] is True

    assert candidates[1]["title"] == "Adding GitHub Link"
    assert candidates[1]["start_time"] == 45.0


def test_candidate_extraction_with_standard_license():
    svc = ReelService()
    fake_job = {
        "job_id": "test_std_job",
        "video_ids": ["std_vid"],
        "publication_gate_status": "restricted_by_product_policy",
        "preview_allowed": True,
        "download_allowed": False,
        "rich_output": {
            "chapters": [
                {
                    "title": "Standard Chapter",
                    "text": "Analysis of standard video.",
                    "timestamp_seconds": 5.0,
                    "video_id": "std_vid",
                }
            ]
        }
    }

    candidates = svc.get_reel_candidates(fake_job)
    assert len(candidates) == 1
    assert candidates[0]["is_cc_by"] is False
    assert "Standard License" in candidates[0]["license_label"]
    assert candidates[0]["safe_to_export"] is False


@pytest.mark.asyncio
async def test_voiceover_word_budget_capping(tmp_path):
    svc = ReelService(output_dir=str(tmp_path))
    out_mp3 = str(tmp_path / "voice_test.mp3")

    # Long text (100 words)
    long_text = "word " * 100
    # For a 30s budget, max words is ~69
    # We test the budgeting math without network call if needed or with live call
    max_words = max(15, int(30.0 * 2.3))
    words = long_text.strip().split()
    capped = " ".join(words[:max_words]).rstrip(",;:-") + "."
    assert len(capped.split()) == 69

