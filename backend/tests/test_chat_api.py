"""
Unit and integration tests for the Video Chat & Q&A API.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, patch, MagicMock
import numpy as np

from backend.main import app


@pytest.fixture
def mock_job_data():
    return {
        "job_id": "test-chat-job-123",
        "status": "completed",
        "video_ids": ["vid_abc"],
        "highlight_segments": [
            {
                "video_id": "vid_abc",
                "start_time": 120.0,
                "end_time": 150.0,
                "text": "Gradient descent minimizes the cost function by taking steps proportional to the negative gradient.",
            },
            {
                "video_id": "vid_abc",
                "start_time": 200.0,
                "end_time": 230.0,
                "text": "The learning rate controls the step size taken in the direction of the steepest descent.",
            },
        ],
        "fusion_metadata": {
            "topics_found": ["Gradient Descent", "Learning Rate", "Cost Function"],
        },
        "rights_snapshot": {
            "vid_abc": {
                "channel_title": "AI Academy",
            }
        },
    }


@pytest.mark.asyncio
async def test_chat_suggestions_success(mock_job_data):
    mock_db = MagicMock()
    mock_db["jobs"].find_one = AsyncMock(return_value=mock_job_data)

    with patch("backend.api.chat.get_database", return_value=mock_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/chat/test-chat-job-123/suggestions")
            assert resp.status_code == 200
            data = resp.json()
            assert data["job_id"] == "test-chat-job-123"
            assert len(data["suggestions"]) >= 3
            assert any("Gradient Descent" in s for s in data["suggestions"])


@pytest.mark.asyncio
async def test_chat_suggestions_not_found():
    mock_db = MagicMock()
    mock_db["jobs"].find_one = AsyncMock(return_value=None)

    with patch("backend.api.chat.get_database", return_value=mock_db):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v1/chat/non-existent/suggestions")
            assert resp.status_code == 404
            assert "Job not found" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_chat_ask_relevant_question(mock_job_data):
    mock_db = MagicMock()
    mock_db["jobs"].find_one = AsyncMock(return_value=mock_job_data)

    mock_embedder = MagicMock()
    # Mock embeddings: 2 segments -> shape (2, 4), query -> shape (4,)
    seg_vecs = np.array([
        [0.9, 0.1, 0.0, 0.0],
        [0.1, 0.9, 0.0, 0.0],
    ])
    q_vec = np.array([0.95, 0.05, 0.0, 0.0])

    def fake_encode(text_or_texts, **kwargs):
        if isinstance(text_or_texts, list):
            return seg_vecs
        return q_vec

    mock_embedder.encode = MagicMock(side_effect=fake_encode)

    with patch("backend.api.chat.get_database", return_value=mock_db), \
         patch("backend.api.chat.get_sentence_transformer", return_value=mock_embedder), \
         patch.dict("backend.api.chat._JOB_EMBEDDINGS_CACHE", {}, clear=True):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/chat/test-chat-job-123/ask",
                json={"question": "What does gradient descent minimize?"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["found"] is True
            assert data["confidence"] == "high"
            assert len(data["citations"]) > 0
            citation = data["citations"][0]
            assert citation["video_id"] == "vid_abc"
            assert citation["video_title"] == "AI Academy"
            assert citation["timestamp_label"] == "02:00"
            assert "minimizes the cost function" in citation["snippet"]
            assert "According to the source video" in data["answer"]


@pytest.mark.asyncio
async def test_chat_ask_empty_question():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat/test-chat-job-123/ask",
            json={"question": ""},
        )
        assert resp.status_code == 422  # Pydantic validation error for min_length
