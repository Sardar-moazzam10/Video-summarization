import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from backend.main import app
from backend.core.security import get_current_user

def test_transcript_endpoint_invokes_service_exactly_once():
    """
    Regression test for Batch 0:
    Ensure /api/v1/transcript calls get_transcript on TranscriptService
    exactly once with the provided allow_whisper and fast_search parameters.
    """
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user_id"}
    
    mock_service = AsyncMock()
    mock_service.get_transcript.return_value = {
        "transcript": [{"text": "Hello world", "start": 0.0, "duration": 2.0}],
        "source": "youtube_api_fast",
        "cached": False,
    }
    
    with patch("backend.api.transcript.get_transcript_service", return_value=mock_service):
        client = TestClient(app)
        response = client.get(
            "/api/v1/transcript?videoId=dQw4w9WgXcQ&allow_whisper=false&fast_search=true"
        )
        
        assert response.status_code == 200
        assert response.json()["source"] == "youtube_api_fast"
        assert mock_service.get_transcript.call_count == 1
        mock_service.get_transcript.assert_called_once_with(
            "dQw4w9WgXcQ",
            allow_whisper=False,
            fast_search=True,
        )
    
    app.dependency_overrides.clear()

