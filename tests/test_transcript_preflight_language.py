import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.transcript_service import TranscriptService


def _service_with_cached(transcript):
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value={
        "video_id": "source12345",
        "transcript": transcript,
        "source": "cache",
    })
    db = MagicMock()
    collection.update_one = AsyncMock()
    db.__getitem__.return_value = collection
    return TranscriptService(db)


@pytest.mark.asyncio
async def test_english_transcript_preflight_is_ready():
    service = _service_with_cached([
        {"text": "This is a supported English transcript.", "start": 0.0, "duration": 4.0}
    ])
    with patch.object(service, "_detect_transcript_language", return_value="en"):
        result = await service.preflight_source("source12345")

    assert result["ready"] is True
    assert result["detected_language"] == "en"
    assert result["supported_languages"] == ["en"]
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_hindi_transcript_preflight_does_not_reject_before_normalization():
    service = _service_with_cached([
        {"text": "यह हिंदी प्रतिलेख है", "start": 0.0, "duration": 4.0}
    ])
    with patch.object(service, "_detect_transcript_language", return_value="hi"):
        result = await service.preflight_source("source12345")

    assert result["video_id"] == "source12345"
    assert result["source_id"] == "source12345"
    assert result["status"] == "translation_required"
    assert result["ready"] is True
    assert result["method"] == "cache"
    assert result["detected_language"] == "hi"
    assert result["supported_languages"] == ["en"]
    assert result["error_code"] is None


@pytest.mark.asyncio
async def test_hindi_cached_transcript_is_canonicalized_before_return():
    service = _service_with_cached([
        {"text": "यह हिंदी प्रतिलेख है", "start": 0.0, "duration": 4.0}
    ])

    translated = [{"text": "This is an English transcript.", "start": 0.0, "duration": 4.0}]

    def detect_by_content(rows):
        return "hi" if any("हिंदी" in row.get("text", "") for row in rows) else "en"

    with patch.object(service, "_detect_transcript_language", side_effect=detect_by_content):
        with patch.object(service, "_translate_transcript_to_english", return_value=translated):
            result = await service.get_transcript("source12345", allow_whisper=False)

    assert result is not None
    assert [segment["text"] for segment in result["transcript"]] == ["This is an English transcript."]
    assert result["transcript"][0]["language"] == "en"
    assert result["transcript"][0]["translation_method"] == "text_translation"
    assert result["source"] == "cache+translated"
    assert result["cached"] is False  # source captions were cached; canonical English was newly generated


@pytest.mark.asyncio
async def test_non_english_captions_uses_fast_text_translation_and_skips_whisper_even_when_allow_whisper_true():
    """Verify that when captions exist, text translation runs first and Whisper is NOT called."""
    service = _service_with_cached([
        {"text": "यह हिंदी प्रतिलेख है", "start": 0.0, "duration": 4.0}
    ])

    translated = [{"text": "This is an English transcript.", "start": 0.0, "duration": 4.0}]

    def detect_by_content(rows):
        return "hi" if any("हिंदी" in row.get("text", "") for row in rows) else "en"

    recover_whisper_mock = AsyncMock()

    with patch.object(service, "_detect_transcript_language", side_effect=detect_by_content):
        with patch.object(service, "_translate_transcript_to_english", return_value=translated):
            with patch.object(service, "_recover_whisper", recover_whisper_mock):
                result = await service.get_transcript("source12345", allow_whisper=True)

    assert result is not None
    assert result["source"] == "cache+translated"
    assert recover_whisper_mock.call_count == 0, "Whisper must NOT be called when text translation succeeds!"


@pytest.mark.asyncio
async def test_long_video_skips_whisper_to_prevent_cpu_freeze():
    """Verify that a 2-hour (7200s) video skips Whisper STT fallback to prevent 15-minute CPU hang."""
    service = _service_with_cached([])

    with patch("backend.services.transcript_service.get_video_duration_seconds", return_value=7200.0, create=True), \
         patch("backend.services.media_probe.get_video_duration_seconds", return_value=7200.0):
        whisper_result = await service._recover_whisper("long_video_123", language="hi")

    assert whisper_result is None, "Whisper recovery must safely return None for long videos (>1200s)"


@pytest.mark.asyncio
async def test_preflight_flags_long_video_without_captions_as_audio_transcription_exceeded():
    """Verify preflight rejects videos exceeding Whisper CPU limit when captions are absent."""
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=None)
    db = MagicMock()
    db.__getitem__.return_value = collection
    service = TranscriptService(db)

    with patch.object(service, "_fetch_youtube_api", return_value=None), \
         patch.object(service, "_fetch_ytdlp", return_value=None), \
         patch("backend.services.media_probe.get_video_duration_seconds", return_value=7200.0):
        result = await service.preflight_source("long_video_123")

    assert result["ready"] is False
    assert result["error_code"] == "AUDIO_TRANSCRIPTION_EXCEEDED"
    assert "exceeds audio transcription limit" in result["error"]
