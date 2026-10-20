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
