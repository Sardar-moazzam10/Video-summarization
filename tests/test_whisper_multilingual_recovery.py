"""Whisper-first multilingual transcript recovery regression coverage."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.transcript_service import TranscriptService


VIDEO_ID = "source12345"
HINDI = [{"text": "यह हिंदी भाषा का विस्तृत प्रतिलेख है", "start": 0.0, "duration": 5.0}]
ENGLISH = [{"text": "This is a detailed English transcript for the lesson.", "start": 0.0, "duration": 900.0}]


def make_service(cached=None):
    collection = MagicMock()
    collection.find_one = AsyncMock(return_value=cached)
    collection.update_one = AsyncMock()
    db = MagicMock()
    db.__getitem__.return_value = collection
    return TranscriptService(db), collection


@pytest.fixture(autouse=True)
def no_acquisition_io():
    with patch("backend.services.transcript_service.append_event", new_callable=AsyncMock):
        yield


@pytest.mark.asyncio
async def test_native_english_captions_do_not_call_whisper():
    service, _ = make_service()
    with patch.object(service, "_fetch_youtube_api", return_value=ENGLISH), \
         patch.object(service, "_recover_whisper") as whisper:
        result = await service.get_transcript(VIDEO_ID)
    assert result["source"] == "youtube_api"
    assert result["transcript"][0]["language"] == "en"
    whisper.assert_not_called()


@pytest.mark.asyncio
async def test_youtube_translated_english_does_not_call_whisper():
    service, _ = make_service()
    translated = [{"text": "YouTube supplied reliable translated English captions.", "start": 0, "duration": 5}]
    with patch.object(service, "_fetch_youtube_api", return_value=translated), \
         patch.object(service, "_recover_whisper") as whisper:
        result = await service.get_transcript(VIDEO_ID)
    assert result["transcript"][0]["translation_method"] == "youtube"
    whisper.assert_not_called()


@pytest.mark.asyncio
async def test_hindi_captions_invoke_whisper_before_text_translation():
    service, collection = make_service()
    with patch.object(service, "_fetch_youtube_api", return_value=HINDI), \
         patch.object(service, "_recover_whisper", return_value=service._canonicalize_segments(
             ENGLISH, VIDEO_ID, original_language="hi",
             provenance="whisper_audio_translation", translation_method="whisper",
         )) as whisper, \
         patch.object(service, "_translate_transcript_to_english") as text_translate:
        result = await service.get_transcript(VIDEO_ID)
    whisper.assert_called_once_with(VIDEO_ID, "hi", None)
    text_translate.assert_not_called()
    assert result["source"] == "whisper_translate"
    payload = collection.update_one.await_args.args[1]["$set"]
    assert payload["translation_method"] == "whisper"
    assert payload["whisper_cache_identity"].startswith("openai-whisper:")


@pytest.mark.asyncio
async def test_too_many_requests_is_irrelevant_when_whisper_works():
    service, _ = make_service()
    whisper_en = service._canonicalize_segments(
        ENGLISH, VIDEO_ID, original_language="hi",
        provenance="whisper_audio_translation", translation_method="whisper",
    )
    with patch.object(service, "_fetch_youtube_api", return_value=HINDI), \
         patch.object(service, "_recover_whisper", return_value=whisper_en), \
         patch.object(service, "_translate_transcript_to_english", side_effect=RuntimeError("TooManyRequests")) as google:
        result = await service.get_transcript(VIDEO_ID)
    assert result["source"] == "whisper_translate"
    google.assert_not_called()


@pytest.mark.asyncio
async def test_source_longer_than_old_eight_minute_gate_reaches_whisper():
    service, _ = make_service()
    long_hindi = [{"text": HINDI[0]["text"], "start": 0, "duration": 3600}]
    whisper_en = service._canonicalize_segments(
        ENGLISH, VIDEO_ID, original_language="hi",
        provenance="whisper_audio_translation", translation_method="whisper",
    )
    with patch.object(service, "_fetch_youtube_api", return_value=long_hindi), \
            patch.object(service, "_translate_transcript_to_english", return_value=long_hindi), \
         patch.object(service, "_recover_whisper", return_value=whisper_en) as whisper:
        result = await service.get_transcript(VIDEO_ID)
    whisper.assert_called_once()
    assert result["source"] == "whisper_translate"


@pytest.mark.asyncio
async def test_long_non_english_captions_use_whisper_before_text_fallback():
    service, _ = make_service()
    long_hindi = [{"text": HINDI[0]["text"], "start": 0.0, "duration": 900.0}]
    whisper_en = service._canonicalize_segments(
        ENGLISH, VIDEO_ID, original_language="hi",
        provenance="whisper_audio_translation", translation_method="whisper",
    )
    with patch.object(service, "_fetch_youtube_api", return_value=long_hindi), \
         patch.object(service, "_recover_whisper", return_value=whisper_en) as whisper, \
         patch.object(service, "_translate_transcript_to_english") as text_translate:
        result = await service.get_transcript(VIDEO_ID)
    whisper.assert_called_once_with(VIDEO_ID, "hi", None)
    text_translate.assert_not_called()
    assert result["source"] == "whisper_translate"
    assert result["transcript"][0]["translation_method"] == "whisper"


def test_long_audio_global_timestamps_and_overlap_dedup(monkeypatch):
    service, _ = make_service()
    service._whisper_model = MagicMock()
    service._whisper_model.transcribe.side_effect = [
        {"segments": [{"text": "boundary phrase", "start": 58.5, "end": 60.0}]},
        {"segments": [
            {"text": "boundary phrase", "start": 0.0, "end": 1.0},
            {"text": "second idea", "start": 2.0, "end": 4.0},
        ]},
        {"segments": [{"text": "final idea", "start": 0.0, "end": 2.0}]},
    ]
    settings = SimpleNamespace(
        WHISPER_CHUNK_SECONDS=60.0,
        WHISPER_CHUNK_OVERLAP_SECONDS=1.0,
        FFMPEG_PATH="/usr/bin/ffmpeg",
    )
    monkeypatch.setattr("backend.core.config.get_settings", lambda: settings)
    monkeypatch.setattr(service, "_audio_duration_seconds", lambda _: 121.0)
    monkeypatch.setattr(
        "backend.services.transcript_service.run_subprocess_safe",
        lambda *a, **k: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )
    result, chunks = service._transcribe_audio_chunks("/tmp/fake.mp3", VIDEO_ID, "hi")
    assert chunks == 3
    assert [item["text"] for item in result].count("boundary phrase") == 1
    assert [item["start"] for item in result] == sorted(item["start"] for item in result)
    assert all(0 <= item["start"] <= item["end"] <= 121.0 for item in result)
    assert next(item for item in result if item["text"] == "second idea")["start"] == pytest.approx(61.0)
    assert all(item["translation_method"] == "whisper" for item in result)


def test_unknown_audio_duration_fails_safe_instead_of_loading_full_file(monkeypatch):
    service, _ = make_service()
    service._whisper_model = MagicMock()
    settings = SimpleNamespace(
        WHISPER_CHUNK_SECONDS=900.0,
        WHISPER_CHUNK_OVERLAP_SECONDS=1.0,
        FFMPEG_PATH="/usr/bin/ffmpeg",
    )
    monkeypatch.setattr("backend.core.config.get_settings", lambda: settings)
    monkeypatch.setattr(service, "_audio_duration_seconds", lambda _: None)
    with pytest.raises(RuntimeError, match="duration is required"):
        service._transcribe_audio_chunks("/tmp/fake.mp3", VIDEO_ID, "hi")
    service._whisper_model.transcribe.assert_not_called()


@pytest.mark.asyncio
async def test_whisper_failure_attempts_text_fallback():
    service, _ = make_service()
    translated = [{"text": "The fallback produced English text.", "start": 0, "duration": 5}]
    with patch.object(service, "_fetch_youtube_api", return_value=HINDI), \
         patch.object(service, "_recover_whisper", return_value=None), \
         patch.object(service, "_translate_transcript_to_english", return_value=translated) as fallback:
        result = await service.get_transcript(VIDEO_ID)
    fallback.assert_called_once()
    assert result["source"] == "youtube_api+translated"
    assert result["transcript"][0]["translation_method"] == "text_translation"


@pytest.mark.asyncio
async def test_all_translation_paths_fail_returns_non_english_for_structured_gate():
    service, _ = make_service()
    with patch.object(service, "_fetch_youtube_api", return_value=HINDI), \
         patch.object(service, "_recover_whisper", return_value=None), \
         patch.object(service, "_translate_transcript_to_english", return_value=HINDI):
        result = await service.get_transcript(VIDEO_ID)
    assert result["source"] == "youtube_api+partial"
    assert service._detect_transcript_language(result["transcript"]) == "hi"


@pytest.mark.asyncio
async def test_cached_whisper_translation_is_reused():
    probe, _ = make_service()
    canonical = probe._canonicalize_segments(
        ENGLISH, VIDEO_ID, original_language="hi",
        provenance="whisper_audio_translation", translation_method="whisper",
    )
    cached = {
        "video_id": VIDEO_ID,
        "transcript": canonical,
        "source": "whisper_translate",
        "whisper_cache_identity": probe._whisper_cache_identity(),
    }
    service, _ = make_service(cached)
    with patch.object(service, "_recover_whisper") as whisper, \
         patch.object(service, "_fetch_youtube_api") as youtube:
        result = await service.get_transcript(VIDEO_ID)
    assert result["cached"] is True
    assert result["source"] == "whisper_translate"
    whisper.assert_not_called()
    youtube.assert_not_called()


@pytest.mark.asyncio
async def test_mixed_sources_both_become_canonical_english():
    from backend.api.merge import fetch_transcripts_with_segments
    service, _ = make_service()

    async def fake_get(video_id, **kwargs):
        if video_id == "english0001":
            transcript = service._canonicalize_segments(ENGLISH, video_id, provenance="youtube_api")
            return {"transcript": transcript, "source": "youtube_api", "cached": False}
        transcript = service._canonicalize_segments(
            ENGLISH, video_id, original_language="hi",
            provenance="whisper_audio_translation", translation_method="whisper",
        )
        return {"transcript": transcript, "source": "whisper_translate", "cached": False}

    service.get_transcript = fake_get
    with patch("backend.services.transcript_service.get_transcript_service", new=AsyncMock(return_value=service)):
        texts, segments = await fetch_transcripts_with_segments(["english0001", "hindi000001"])
    assert set(texts) == {"english0001", "hindi000001"}
    assert all(segment["language"] == "en" for rows in segments.values() for segment in rows)
    assert segments["hindi000001"][0]["translation_method"] == "whisper"
