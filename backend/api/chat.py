"""
Chat with Video API — Ask questions about video content.

Uses FAISS vector store for semantic retrieval + Ollama for answer synthesis.
Falls back to raw FAISS segments when Ollama is unavailable.

Endpoints:
- POST /api/v1/chat - Ask a question about processed video content
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


# =====================================================
# REQUEST / RESPONSE MODELS
# =====================================================

class ChatRequest(BaseModel):
    """Request to ask a question about video content."""
    question: str = Field(..., min_length=1, max_length=1000)
    video_ids: Optional[List[str]] = None  # None = search all indexed videos
    top_k: int = Field(default=5, ge=1, le=20)


class SourceInfo(BaseModel):
    """A source segment that contributed to the answer."""
    text: str
    video_id: str
    video_title: str
    score: float
    timestamp: Optional[float] = None


class ChatResponse(BaseModel):
    """Response with AI-generated answer and source attributions."""
    answer: str
    sources: List[SourceInfo]
    question: str


# =====================================================
# ENDPOINT
# =====================================================

@router.post("", response_model=ChatResponse)
async def chat_with_video(request: ChatRequest):
    """
    Ask a natural-language question about previously processed videos.

    1. Retrieves relevant transcript segments via FAISS semantic search
    2. Sends context + question to Ollama for answer synthesis
    3. Returns structured answer with source attributions

    Videos must be processed first (via the merge pipeline) to be searchable.
    """
    from ..services.vector_store import get_vector_store
    from ..services.ollama_service import get_ollama_service

    store = get_vector_store()

    if store.index is None or store.index.ntotal == 0:
        return ChatResponse(
            answer="Videos are still being indexed. Please wait a moment and try again.",
            sources=[],
            question=request.question,
        )

    # Step 1: Retrieve relevant segments from FAISS
    results = store.search(request.question, top_k=request.top_k)

    # Filter by video_ids if specified
    if request.video_ids:
        results = [r for r in results if r["video_id"] in request.video_ids]

    if not results:
        return ChatResponse(
            answer="I could not find relevant information about this topic in the indexed videos.",
            sources=[],
            question=request.question,
        )

    # Step 2: Build context from retrieved segments
    context = "\n\n".join(
        f"[From: {r.get('video_title', r['video_id'])}] {r['text']}"
        for r in results
    )

    # Step 3: Generate answer with Ollama (or fall back to raw FAISS segments)
    ollama = get_ollama_service()
    answer = None
    if ollama.is_available():
        answer = await ollama.answer_question(request.question, context)

    if not answer:
        # Local fallback: stitch the top retrieved segments into a direct answer
        top_texts = [r["text"] for r in results[:3]]
        answer = " [...] ".join(top_texts)
        if len(answer) > 800:
            answer = answer[:800] + "..."

    # Step 4: Build response
    sources = [
        SourceInfo(
            text=r["text"][:300],
            video_id=r["video_id"],
            video_title=r.get("video_title", r["video_id"]),
            score=r.get("score", 0.0),
            timestamp=r.get("timestamp"),
        )
        for r in results
    ]

    return ChatResponse(
        answer=answer,
        sources=sources,
        question=request.question,
    )
