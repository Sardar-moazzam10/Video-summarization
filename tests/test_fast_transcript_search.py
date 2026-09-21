"""
Tests for dedicated fast transcript-search path (Deep Search / Keyword Search).

Invariants verified:
1. fast_search=True / allow_whisper=False never invokes Whisper, yt-dlp, or audio download.
2. Hindi-only (non-English) captions are skipped quickly without translation attempts.
3. Subtitle-disabled / unavailable videos fail fast without retries.
4. English captions (manual & auto-generated) remain searchable.
5. Cached English transcripts are returned without refetching.
6. One failed/skipped video does not block concurrent fetches.
"""
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound

from backend.services.transcript_service import TranscriptService


class MockAsyncCollection:
    """Mock MongoDB async collection for unit testing."""
    def __init__(self, initial_data=None):
        self.data = initial_data or {}

    async def find_one(self, query):
        vid = query.get("video_id")
        return self.data.get(vid)

    async def update_one(self, query, update, upsert=False):
        vid = query.get("video_id")
        set_data = update.get("$set", {})
        self.data[vid] = set_data
        return MagicMock(modified_count=1)

    async def delete_one(self, query):
        vid = query.get("video_id")
        deleted = 1 if vid in self.data else 0
        self.data.pop(vid, None)
        return MagicMock(deleted_count=deleted)


class MockTranscriptItem:
    def __init__(self, language_code, is_generated=False):
        self.language_code = language_code
        self.is_generated = is_generated

    def fetch(self):
        return [
            {"text": "Linear regression models relationships.", "start": 0.0, "duration": 4.0},
            {"text": "Logistic regression is used for classification.", "start": 4.5, "duration": 3.5},
        ]


class MockTranscriptList:
    def __init__(self, transcripts):
        self.transcripts = transcripts

    def __iter__(self):
        return iter(self.transcripts)

    def find_manually_created_transcript(self, language_codes):
        for t in self.transcripts:
            if not t.is_generated and t.language_code in language_codes:
                return t
        raise NoTranscriptFound("en", language_codes)

    def find_generated_transcript(self, language_codes):
        for t in self.transcripts:
            if t.is_generated and t.language_code in language_codes:
                return t
        raise NoTranscriptFound("en", language_codes)


@pytest.fixture
def transcript_service():
    mock_db = {"transcripts": MockAsyncCollection()}
    return TranscriptService(mock_db)


@pytest.mark.asyncio
async def test_fast_search_never_calls_whisper_or_ytdlp(transcript_service):
    """fast_search=True must never invoke Whisper, yt-dlp, or audio download."""
    with patch("backend.services.transcript_service.YouTubeTranscriptApi") as mock_ytt_class, \
         patch.object(transcript_service, "_fetch_whisper") as mock_whisper, \
         patch.object(transcript_service, "_fetch_ytdlp") as mock_ytdlp, \
         patch.object(transcript_service, "_translate_transcript_to_english") as mock_translate:

        mock_ytt_instance = mock_ytt_class.return_value
        mock_ytt_instance.list.side_effect = TranscriptsDisabled("OCwZyYH14uw")

        result = await transcript_service.get_transcript(
            "OCwZyYH14uw",
            allow_whisper=False,
            fast_search=True
        )

        assert result is None
        mock_whisper.assert_not_called()
        mock_ytdlp.assert_not_called()
        mock_translate.assert_not_called()


@pytest.mark.asyncio
async def test_hindi_only_captions_skipped_without_translation(transcript_service):
    """Non-English captions must be skipped quickly without invoking translation or Whisper."""
    with patch("backend.services.transcript_service.YouTubeTranscriptApi") as mock_ytt_class, \
         patch.object(transcript_service, "_fetch_whisper") as mock_whisper, \
         patch.object(transcript_service, "_translate_transcript_to_english") as mock_translate:

        mock_ytt_instance = mock_ytt_class.return_value
        # Video only has Hindi captions
        mock_ytt_instance.list.return_value = MockTranscriptList([
            MockTranscriptItem("hi", is_generated=False)
        ])

        result = await transcript_service.get_transcript(
            "hindi_vid_123",
            allow_whisper=False,
            fast_search=True
        )

        assert result is None
        mock_translate.assert_not_called()
        mock_whisper.assert_not_called()


@pytest.mark.asyncio
async def test_transcripts_disabled_fails_fast(transcript_service):
    """Disabled transcripts must fail fast with zero retries."""
    with patch("backend.services.transcript_service.YouTubeTranscriptApi") as mock_ytt_class:
        mock_ytt_instance = mock_ytt_class.return_value
        mock_ytt_instance.list.side_effect = TranscriptsDisabled("disabled_vid")

        result = await transcript_service.get_transcript(
            "disabled_vid",
            allow_whisper=False,
            fast_search=True
        )

        assert result is None
        # Must only call list() exactly once — no backoff / retry loops
        assert mock_ytt_instance.list.call_count == 1


@pytest.mark.asyncio
async def test_english_captions_remain_searchable(transcript_service):
    """English captions (manual or auto) must be fetched and formatted properly."""
    with patch("backend.services.transcript_service.YouTubeTranscriptApi") as mock_ytt_class:
        mock_ytt_instance = mock_ytt_class.return_value
        mock_ytt_instance.list.return_value = MockTranscriptList([
            MockTranscriptItem("en", is_generated=True)
        ])

        result = await transcript_service.get_transcript(
            "english_vid_123",
            allow_whisper=False,
            fast_search=True
        )

        assert result is not None
        assert result["source"] == "youtube_api_fast"
        assert result["cached"] is False
        assert len(result["transcript"]) == 2
        assert "Linear regression" in result["transcript"][0]["text"]


@pytest.mark.asyncio
async def test_cached_searches_avoid_refetching(transcript_service):
    """Cached English transcripts must be returned without making any network calls."""
    # Pre-populate cache
    cached_doc = {
        "video_id": "cached_vid_456",
        "transcript": [
            {"text": "This is cached English content.", "start": 0.0, "duration": 5.0}
        ],
        "source": "cache",
        "fetched_at": "2026-09-20T20:00:00Z"
    }
    transcript_service.transcripts.data["cached_vid_456"] = cached_doc

    with patch.object(transcript_service, "_fetch_fast_english_transcript") as mock_fetch:
        result = await transcript_service.get_transcript(
            "cached_vid_456",
            allow_whisper=False,
            fast_search=True
        )

        assert result is not None
        assert result["cached"] is True
        assert result["transcript"] == cached_doc["transcript"]
        mock_fetch.assert_not_called()


@pytest.mark.asyncio
async def test_one_failed_video_does_not_block_the_rest(transcript_service):
    """Concurrent fetches must allow succeeding videos to complete even if others fail or are skipped."""
    with patch("backend.services.transcript_service.YouTubeTranscriptApi") as mock_ytt_class:
        mock_ytt_instance = mock_ytt_class.return_value

        def list_side_effect(vid_id):
            if vid_id == "vid_disabled":
                raise TranscriptsDisabled(vid_id)
            elif vid_id == "vid_hindi":
                return MockTranscriptList([MockTranscriptItem("hi")])
            elif vid_id == "vid_english":
                return MockTranscriptList([MockTranscriptItem("en")])
            raise ValueError(f"Unknown {vid_id}")

        mock_ytt_instance.list.side_effect = list_side_effect

        results = await asyncio.gather(
            transcript_service.get_transcript("vid_disabled", allow_whisper=False, fast_search=True),
            transcript_service.get_transcript("vid_hindi", allow_whisper=False, fast_search=True),
            transcript_service.get_transcript("vid_english", allow_whisper=False, fast_search=True),
        )

        assert results[0] is None  # Disabled video skipped fast
        assert results[1] is None  # Hindi video skipped fast
        assert results[2] is not None  # English video succeeded
        assert results[2]["source"] == "youtube_api_fast"

