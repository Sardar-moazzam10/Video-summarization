"""
Tests for translation_service — bounded retry/timeout behavior on the
Google-translate fast path.

Regression coverage for a real incident: a Hindi transcript whose captions
triggered repeated TranslationNotFound errors caused the whole merge job to
stall for 7+ minutes at 5% progress, because a chunk failure fell back to
translating every segment in that chunk individually (no bound), and the
whole thing ran synchronously on the request event loop.

Everything here is mocked. No test depends on a live translation API.
"""

import time

import pytest

from backend.services import translation_service as ts


class _FakeSettings:
    """Small timeouts so tests run in well under a second instead of
    waiting out the real 8s/60s production defaults."""

    def __init__(self, request_timeout=0.05, stage_timeout=0.3,
                 circuit_breaker_failures=3, nllb_max_segments=30):
        self.TRANSLATION_REQUEST_TIMEOUT_SECONDS = request_timeout
        self.TRANSLATION_STAGE_TIMEOUT_SECONDS = stage_timeout
        self.TRANSLATION_CIRCUIT_BREAKER_FAILURES = circuit_breaker_failures
        self.NLLB_MAX_SEGMENTS_FOR_FALLBACK = nllb_max_segments


@pytest.fixture(autouse=True)
def fast_settings(monkeypatch):
    import backend.core.config as config_module

    monkeypatch.setattr(config_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(ts, "_GOOGLE_PAUSE_SECONDS", 0)
    # Whenever the Google path gives up (>half the segments failed), the
    # caller falls back to local NLLB — which would otherwise try to
    # download a ~2.4GB model from HuggingFace. Force that path off so a
    # test can never trigger a live network call by accident; the NLLB
    # fallback itself is out of scope here.
    monkeypatch.setattr(ts, "_load_nllb", lambda: None)


def _install_fake_translator(monkeypatch, translate_fn):
    """Swap deep_translator.GoogleTranslator for a fake whose .translate()
    is `translate_fn(text) -> str`."""

    class FakeGoogleTranslator:
        def __init__(self, source="auto", target="en"):
            self.source = source
            self.target = target

        def translate(self, text):
            return translate_fn(text)

    import deep_translator

    monkeypatch.setattr(deep_translator, "GoogleTranslator", FakeGoogleTranslator)


class TestNormalTranslation:
    """A: translation succeeds normally."""

    def test_translation_succeeds(self, monkeypatch):
        def echo_upper(text):
            return "\n".join(line.upper() for line in text.split("\n"))

        _install_fake_translator(monkeypatch, echo_upper)

        texts = [f"segment {i}" for i in range(6)]
        result = ts._translate_segments_google(texts, "hi")

        assert result is not None
        assert len(result) == len(texts)
        assert result[0] == "SEGMENT 0"
        assert result[-1] == "SEGMENT 5"


class TestChunkRetry:
    """B: one chunk fails once, retry succeeds."""

    def test_chunk_fails_once_then_succeeds(self, monkeypatch):
        calls = {"n": 0}

        def flaky(text):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("transient")
            return "\n".join(line.upper() for line in text.split("\n"))

        _install_fake_translator(monkeypatch, flaky)

        # Short enough to land in a single 2000-char chunk.
        texts = ["segment 0", "segment 1", "segment 2"]
        result = ts._translate_segments_google(texts, "hi")

        assert result is not None
        assert len(result) == len(texts)
        assert result[0] == "SEGMENT 0"
        assert calls["n"] == 2  # exactly one retry — no more


class TestPermanentChunkFailure:
    """C: one chunk fails permanently. No infinite retry; the chunk is
    marked failed and the run continues rather than cascading into a
    per-segment retry storm."""

    def test_no_infinite_retry_and_no_per_segment_cascade(self, monkeypatch):
        calls = {"n": 0}

        def always_fails(text):
            calls["n"] += 1
            raise ConnectionError("down")

        _install_fake_translator(monkeypatch, always_fails)

        texts = ["segment 0", "segment 1", "segment 2"]
        start = time.monotonic()
        result = ts._translate_segments_google(texts, "hi")
        elapsed = time.monotonic() - start

        # One chunk (all 3 texts fit under 2000 chars) => exactly 2 calls
        # (first attempt + one retry). NOT 3 additional per-segment calls —
        # that cascade is exactly what caused the original 7+ minute stall.
        assert calls["n"] == 2
        assert elapsed < 2.0
        # Every segment untranslated => signal to the caller (>half failed)
        # to fall back to NLLB/original rather than ship a half-translation.
        assert result is None


class TestCircuitBreaker:
    """Regression test for the second real-world incident: with the
    permanent-chunk-failure fix alone, a systemically blocked Google
    (many chunks in a row all hard-failing) still ground through the full
    stage-timeout budget one doomed chunk at a time. The circuit breaker
    must give up after N consecutive whole-chunk failures, well before the
    stage budget or the full segment list is exhausted."""

    def test_gives_up_after_consecutive_failures_not_stage_budget(self, monkeypatch):
        import backend.core.config as config_module

        # Generous stage budget (5s) so the CIRCUIT BREAKER — not the budget
        # — is what has to stop this run.
        monkeypatch.setattr(
            config_module, "get_settings",
            lambda: _FakeSettings(request_timeout=0.05, stage_timeout=5.0,
                                   circuit_breaker_failures=2),
        )

        calls = {"n": 0}

        def always_fails(text):
            calls["n"] += 1
            raise ConnectionError("blocked")

        _install_fake_translator(monkeypatch, always_fails)
        monkeypatch.setattr(ts, "_GOOGLE_MAX_CHARS", 1)  # one segment per chunk

        texts = [f"s{i}" for i in range(100)]
        start = time.monotonic()
        result = ts._translate_segments_google(texts, "hi")
        elapsed = time.monotonic() - start

        # circuit_breaker_failures=2 => exactly 2 chunks attempted (2 calls
        # each = 4 total), not 100 chunks worth (200 calls) and not enough
        # chunks to fill the 5s stage budget either.
        assert calls["n"] == 4
        assert elapsed < 1.0
        assert result is None


class TestAllRequestsTimeout:
    """D: every translation request hangs past the per-request timeout.
    Expected: bounded total execution time, graceful fallback, no stuck
    job."""

    def test_bounded_total_time_when_every_request_hangs(self, monkeypatch):
        def hangs(text):
            time.sleep(5)  # far longer than fast_settings' 0.05s timeout
            return text

        _install_fake_translator(monkeypatch, hangs)

        texts = [f"segment {i}" for i in range(10)]
        start = time.monotonic()
        result = ts._translate_segments_google(texts, "hi")
        elapsed = time.monotonic() - start

        # Bounded by TRANSLATION_STAGE_TIMEOUT_SECONDS (0.3s here), not by
        # 10 segments x 5s of hangs (which would be 50s+ unbounded).
        assert elapsed < 3.0
        assert result is None

    def test_stage_budget_stops_processing_further_chunks(self, monkeypatch):
        """Many small, slow-failing chunks: the stage-wide time budget must
        cut the run short rather than grinding through every chunk."""
        calls = {"n": 0}

        def slow_fail(text):
            calls["n"] += 1
            time.sleep(0.05)
            raise ConnectionError("down")

        _install_fake_translator(monkeypatch, slow_fail)
        # Force one segment per chunk so there are many chunks to grind
        # through if the budget were not enforced.
        monkeypatch.setattr(ts, "_GOOGLE_MAX_CHARS", 1)

        texts = [f"s{i}" for i in range(40)]
        start = time.monotonic()
        result = ts._translate_segments_google(texts, "hi")
        elapsed = time.monotonic() - start

        # Unbounded worst case: 40 chunks x 2 attempts x 0.05s = 4s+.
        # The 0.3s stage budget must cut this off well before that.
        assert elapsed < 2.0
        assert calls["n"] < 40 * 2
        assert result is None


class TestNllbSizeGate:
    """Regression test for the second real-world incident: NLLB-200 was
    benchmarked at ~2.3s/segment on CPU even batched — fine for a short
    clip, but ~57 minutes for a 1467-segment/51-minute video. translate_
    segments() must skip the NLLB fallback outright once the transcript is
    too long for it to plausibly finish in a bounded time, rather than
    starting a multi-minute local-model translation after Google already
    failed."""

    def _force_google_total_failure(self, monkeypatch):
        def always_fails(text):
            raise ConnectionError("blocked")

        _install_fake_translator(monkeypatch, always_fails)

    def test_nllb_skipped_when_transcript_too_long(self, monkeypatch):
        import backend.core.config as config_module

        monkeypatch.setattr(
            config_module, "get_settings",
            lambda: _FakeSettings(request_timeout=0.02, stage_timeout=0.2,
                                   circuit_breaker_failures=1, nllb_max_segments=10),
        )
        self._force_google_total_failure(monkeypatch)

        nllb_calls = {"n": 0}

        def fake_load_nllb():
            nllb_calls["n"] += 1
            return ("fake-tokenizer", "fake-model")

        monkeypatch.setattr(ts, "_load_nllb", fake_load_nllb)

        texts = [f"segment {i}" for i in range(50)]  # > nllb_max_segments (10)
        result = ts.translate_segments(texts, "hi")

        assert nllb_calls["n"] == 0  # NLLB never even loaded, let alone run
        assert result == texts       # best-effort passthrough, unchanged

    def test_nllb_attempted_when_transcript_short_enough(self, monkeypatch):
        import backend.core.config as config_module

        monkeypatch.setattr(
            config_module, "get_settings",
            lambda: _FakeSettings(request_timeout=0.02, stage_timeout=0.2,
                                   circuit_breaker_failures=1, nllb_max_segments=10),
        )
        self._force_google_total_failure(monkeypatch)

        nllb_calls = {"n": 0}

        def fake_load_nllb():
            nllb_calls["n"] += 1
            return ("fake-tokenizer", "fake-model")

        def fake_nllb_segments(texts, flores, tok, model):
            return [f"[EN]{t}" for t in texts]

        monkeypatch.setattr(ts, "_load_nllb", fake_load_nllb)
        monkeypatch.setattr(ts, "_translate_segments_nllb", fake_nllb_segments)

        texts = [f"segment {i}" for i in range(5)]  # <= nllb_max_segments (10)
        result = ts.translate_segments(texts, "hi")

        assert nllb_calls["n"] == 1
        assert result == [f"[EN]segment {i}" for i in range(5)]


class TestPartialFailureTranscript:
    """E: Hindi transcript with partial translation failures. Pipeline does
    not hang, output is deterministic (same input -> same output)."""

    def test_partial_failure_is_deterministic_and_fast(self, monkeypatch):
        def half_broken(text):
            lines = text.split("\n")
            if any("bad" in line for line in lines):
                raise ConnectionError("bad segment")
            return "\n".join(line.upper() for line in lines)

        _install_fake_translator(monkeypatch, half_broken)
        # One segment per chunk so "bad" and "good" segments fail/succeed
        # independently instead of one bad line failing an entire batch.
        monkeypatch.setattr(ts, "_GOOGLE_MAX_CHARS", 1)

        texts = ["good one", "bad segment", "good two", "bad again", "good three"]

        start = time.monotonic()
        result = ts.translate_segments(texts, "hi")
        elapsed = time.monotonic() - start

        assert elapsed < 2.0
        assert len(result) == len(texts)

        result2 = ts.translate_segments(texts, "hi")
        assert result == result2


class TestTranscriptLevelTranslation:
    """translate_transcript_to_english keeps the 1:1 segment/timestamp
    contract even when translation partially fails."""

    def test_length_and_order_preserved_under_partial_failure(self, monkeypatch):
        def half_broken(text):
            lines = text.split("\n")
            if any("bad" in line for line in lines):
                raise ConnectionError("bad segment")
            return "\n".join(line.upper() for line in lines)

        _install_fake_translator(monkeypatch, half_broken)
        monkeypatch.setattr(ts, "_GOOGLE_MAX_CHARS", 1)

        transcript = [
            {"text": "good one", "start": 0.0, "duration": 1.0},
            {"text": "bad segment", "start": 1.0, "duration": 1.0},
            {"text": "good two", "start": 2.0, "duration": 1.0},
        ]

        result = ts.translate_transcript_to_english(transcript, src_lang="hi")

        assert len(result) == 3
        assert [s["start"] for s in result] == [0.0, 1.0, 2.0]
