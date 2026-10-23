import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.api.transcript import summarize_text, SummarizeRequest


@pytest.mark.asyncio
async def test_summarize_text_runs_in_thread_and_caches():
    """Verify endpoint uses threadpool, calls summarize, and caches to Redis."""
    mock_service = MagicMock()
    mock_service.summarize.return_value = "Test summary output."

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # Cache miss first time

    req = SummarizeRequest(text="This is a sufficiently long transcript text for summarization testing.", max_length=150, min_length=50)
    fake_user = {"sub": "user123", "role": "user"}

    with patch("backend.api.transcript.get_transcript_service", AsyncMock(return_value=mock_service)), \
         patch("backend.api.transcript.get_redis_pool", AsyncMock(return_value=mock_redis)), \
         patch("asyncio.to_thread", wraps=__import__("asyncio").to_thread) as mock_to_thread:

        # 1. First call: cache miss -> calls to_thread
        res1 = await summarize_text(req, _user=fake_user)
        assert res1 == {"summary": "Test summary output."}
        assert mock_to_thread.called
        mock_service.summarize.assert_called_once()
        mock_redis.set.assert_called_once()

        # 2. Second call: cache hit -> returns directly from redis without calling summarize again
        mock_redis.get.return_value = b"Cached summary output."
        mock_service.summarize.reset_mock()

        res2 = await summarize_text(req, _user=fake_user)
        assert res2 == {"summary": "Cached summary output."}
        mock_service.summarize.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_text_works_without_redis():
    """Verify endpoint works smoothly if Redis is unavailable."""
    mock_service = MagicMock()
    mock_service.summarize.return_value = "Summary without redis."

    req = SummarizeRequest(text="Test text without redis caching.", max_length=150, min_length=50)
    fake_user = {"sub": "user123", "role": "user"}

    with patch("backend.api.transcript.get_transcript_service", AsyncMock(return_value=mock_service)), \
         patch("backend.api.transcript.get_redis_pool", AsyncMock(return_value=None)):

        res = await summarize_text(req, _user=fake_user)
        assert res == {"summary": "Summary without redis."}
        mock_service.summarize.assert_called_once()


def test_transcript_service_does_not_call_get_summarizer():
    """Verify TranscriptService.summarize() does not call dead T5 get_summarizer."""
    from backend.services.transcript_service import TranscriptService

    db = MagicMock()
    service = TranscriptService(db)

    with patch("backend.services.transcript_service.get_summarizer") as mock_get_sum, \
         patch("backend.services.summarization_service._get_pipeline") as mock_pipeline:

        mock_summarizer_callable = MagicMock(return_value=[{"summary_text": "BART summary"}])
        mock_pipeline.return_value = mock_summarizer_callable

        text = "word " * 150
        result = service.summarize(text)

        assert result == "BART summary"
        mock_get_sum.assert_not_called()
        mock_pipeline.assert_called_once()
