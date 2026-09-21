"""
Summary duration must fit the source video.

A 5m20s video was offering 10/15/20/30-minute summaries and starting the full
merge pipeline for them — download, transcribe, embed, summarise — for a
request that cannot be satisfied by definition. The rule is enforced before
the job exists, and the user is told no rather than silently handed a shorter
summary than the one they asked for.
"""

import pytest
from fastapi import HTTPException

from backend.api import merge as merge_api
from backend.services import media_probe
from backend.services.duration_profiles import DURATION_PROFILES


# =====================================================================
# Eligibility — the rule the UI and the API share
# =====================================================================

class TestEligibleDurations:
    @pytest.mark.parametrize("seconds,expected", [
        (120, []),                     # 2m -> nothing fits
        (300, []),                     # 5m00s -> strict inequality, nothing fits
        (301, [5]),                    # 5m01s -> 5m allowed
        (320, [5]),                    # 5m20s -> only the 5-minute profile
        (599, [5]),                    # 9m59s -> 10 is NOT allowed
        (600, [5]),                    # exactly 10m -> 10 is NOT allowed under strict <
        (601, [5, 10]),                # 10m01s -> 10 is allowed
        (1800, [5, 10, 15, 20]),       # exactly 30m -> 30 is NOT allowed under strict <
        (1801, [5, 10, 15, 20, 30]),   # 30m01s -> 30 is allowed
    ])
    def test_boundaries(self, seconds, expected):
        assert merge_api.eligible_durations(seconds) == expected

    def test_equal_length_is_rejected(self):
        """Invariant: requested_summary_duration < total_unique_selected_source_duration.
        Equal length is rejected."""
        for minutes in DURATION_PROFILES:
            assert minutes not in merge_api.eligible_durations(minutes * 60)


# =====================================================================
# Error payload
# =====================================================================

class TestErrorPayload:
    def test_shape_and_wording_for_5m20s_asking_10m(self):
        payload = merge_api._duration_error(320, 10)
        assert payload["code"] == "SUMMARY_DURATION_EXCEEDS_SOURCE"
        assert payload["error_code"] == "SUMMARY_DURATION_EXCEEDS_SOURCE"
        assert payload["source_duration_seconds"] == 320.0
        assert payload["requested_duration_minutes"] == 10
        assert payload["max_allowed_minutes"] == 5
        assert payload["allowed_durations"] == [5]
        assert "5 minutes or less" in payload["message"]

    def test_source_too_short_for_any_profile(self):
        payload = merge_api._duration_error(120, 5)
        assert payload["code"] == "SUMMARY_DURATION_EXCEEDS_SOURCE"
        assert payload["error_code"] == "SUMMARY_DURATION_EXCEEDS_SOURCE"
        assert payload["max_allowed_minutes"] is None
        assert payload["allowed_durations"] == []
        assert "A 5-minute summary requires more than 5 minutes of source content." in payload["message"]

    @pytest.mark.parametrize("seconds,label", [
        (320, "5m 20s"), (300, "5m"), (45, "45s"), (3661, "61m 1s"),
    ])
    def test_duration_formatting(self, seconds, label):
        assert media_probe.format_duration(seconds) == label


# =====================================================================
# The API boundary — a client cannot bypass this
# =====================================================================

class _Req:
    def __init__(self, video_ids, minutes):
        self.video_ids = video_ids
        self.target_duration_minutes = minutes
        self.generate_audio = True
        self.generate_video = False
        self.highlight_duration_seconds = 120
        self.style = "educational"


@pytest.fixture
def no_job_created(monkeypatch):
    """Fails the test if the expensive pipeline is ever reached."""
    created = []
    monkeypatch.setattr(merge_api, "_active_jobs", {})

    async def _boom():
        created.append(True)
        raise AssertionError("jobs collection touched for an invalid request")

    monkeypatch.setattr(merge_api, "get_jobs_collection", _boom)
    return created


def _fake_durations(monkeypatch, mapping):
    monkeypatch.setattr(merge_api, "get_durations", lambda ids, **kw: mapping)


class TestCreateMergeJobValidation:
    @pytest.mark.asyncio
    async def test_rejects_10m_summary_of_a_5m20s_video(self, monkeypatch, no_job_created):
        _fake_durations(monkeypatch, {"vid1": 320.0})
        with pytest.raises(HTTPException) as exc:
            await merge_api.create_merge_job(_Req(["vid1"], 10), background_tasks=None)
        assert exc.value.status_code == 422
        assert exc.value.detail["error_code"] == "SUMMARY_DURATION_EXCEEDS_SOURCE"
        assert exc.value.detail["max_allowed_minutes"] == 5
        assert not no_job_created, "no job may be created for an invalid duration"

    @pytest.mark.asyncio
    async def test_rejects_5m_summary_of_a_2m_video(self, monkeypatch, no_job_created):
        _fake_durations(monkeypatch, {"vid1": 120.0})
        with pytest.raises(HTTPException) as exc:
            await merge_api.create_merge_job(
                _Req(["vid1"], 5),
                background_tasks=None,
                current_user={"sub": "test-user", "role": "user"},
            )
        assert exc.value.status_code == 422
        assert exc.value.detail["max_allowed_minutes"] is None

    @pytest.mark.asyncio
    async def test_rejects_10m_summary_of_a_9m59s_video(self, monkeypatch, no_job_created):
        _fake_durations(monkeypatch, {"vid1": 599.0})
        with pytest.raises(HTTPException) as exc:
            await merge_api.create_merge_job(_Req(["vid1"], 10), background_tasks=None)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_unresolvable_duration_is_a_graceful_error(self, monkeypatch, no_job_created):
        """Unknown length is not permission to spend minutes finding out."""
        _fake_durations(monkeypatch, {"vid1": None})
        with pytest.raises(HTTPException) as exc:
            await merge_api.create_merge_job(_Req(["vid1"], 10), background_tasks=None)
        assert exc.value.status_code == 422
        assert exc.value.detail["error_code"] == "SOURCE_DURATION_UNAVAILABLE"
        assert exc.value.detail["unresolved_video_ids"] == ["vid1"]

    @pytest.mark.asyncio
    async def test_multi_video_validates_against_combined_length(self, monkeypatch, no_job_created):
        """_allocate_budgets splits the reel across every source in proportion
        to its length, so the pool is the combined material — two 4-minute
        videos can legitimately produce a 5-minute summary."""
        _fake_durations(monkeypatch, {"a": 240.0, "b": 240.0})
        assert merge_api.eligible_durations(480.0) == [5]
        with pytest.raises(HTTPException) as exc:
            await merge_api.create_merge_job(_Req(["a", "b"], 10), background_tasks=None)
        assert exc.value.detail["source_duration_seconds"] == 480.0

    @pytest.mark.asyncio
    async def test_valid_request_passes_validation(self, monkeypatch):
        """5m20s + 5min must NOT be rejected. Stops right after validation —
        reaching the jobs collection proves the duration gate let it through."""
        _fake_durations(monkeypatch, {"vid1": 320.0})
        monkeypatch.setattr(merge_api, "_active_jobs", {})
        reached = {}

        async def _marker():
            reached["yes"] = True
            raise RuntimeError("stop-after-validation")

        monkeypatch.setattr(merge_api, "get_jobs_collection", _marker)
        with pytest.raises(RuntimeError, match="stop-after-validation"):
            await merge_api.create_merge_job(
                _Req(["vid1"], 5),
                background_tasks=None,
                current_user={"sub": "test-user", "role": "user"},
            )
        assert reached.get("yes"), "valid request was rejected by the duration gate"


# =====================================================================
# Probe
# =====================================================================

class TestMediaProbe:
    def test_zero_duration_is_unknown_not_zero_length(self, monkeypatch):
        """A live stream or failed extraction reports 0; treating that as a
        real measurement would reject every duration for that video."""
        media_probe.clear_cache()

        class _P:
            stdout = "0\n"

        monkeypatch.setattr(media_probe.subprocess, "run", lambda *a, **k: _P())
        monkeypatch.setattr(media_probe, "_ytdlp_cmd", lambda: ["yt-dlp"])
        assert media_probe.get_video_duration_seconds("x") is None

    def test_unparseable_output_returns_none(self, monkeypatch):
        media_probe.clear_cache()

        class _P:
            stdout = "NA\n"

        monkeypatch.setattr(media_probe.subprocess, "run", lambda *a, **k: _P())
        monkeypatch.setattr(media_probe, "_ytdlp_cmd", lambda: ["yt-dlp"])
        assert media_probe.get_video_duration_seconds("x") is None

    def test_result_is_cached(self, monkeypatch):
        media_probe.clear_cache()
        calls = {"n": 0}

        class _P:
            stdout = "320\n"

        def _run(*a, **k):
            calls["n"] += 1
            return _P()

        monkeypatch.setattr(media_probe.subprocess, "run", _run)
        monkeypatch.setattr(media_probe, "_ytdlp_cmd", lambda: ["yt-dlp"])
        assert media_probe.get_video_duration_seconds("x") == 320.0
        assert media_probe.get_video_duration_seconds("x") == 320.0
        assert calls["n"] == 1
