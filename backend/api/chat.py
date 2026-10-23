"""
Video Chat & Interactive Q&A API.
Enables users to ask questions grounded in merged video transcripts with clickable timestamp citations.
"""
import asyncio
import re
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
import numpy as np

from ..core.database import get_database
from ..core.security import get_current_user_optional
from ..services.fusion_engine import get_sentence_transformer

router = APIRouter(prefix="/api/v1/chat", tags=["Video Chat & Q&A"])

# In-memory LRU cache for job segment embeddings: job_id -> (segments_hash, embeddings_matrix, segments_list)
_JOB_EMBEDDINGS_CACHE: Dict[str, Dict[str, Any]] = {}


class ChatQueryRequest(BaseModel):
    question: str = Field(..., min_length=2, max_length=500, description="User question about the video(s)")


class CitationItem(BaseModel):
    video_id: str
    video_title: str
    timestamp_seconds: float
    timestamp_label: str
    snippet: str
    score: float


class ChatQueryResponse(BaseModel):
    job_id: str
    question: str
    answer: str
    citations: List[CitationItem]
    found: bool
    confidence: str


class SuggestionsResponse(BaseModel):
    job_id: str
    suggestions: List[str]


def _format_timestamp(seconds: float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    s = max(0, int(seconds))
    hrs = s // 3600
    mins = (s % 3600) // 60
    secs = s % 60
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def _clean_snippet(text: str, max_words: int = 40) -> str:
    """Format and clean spoken transcript snippet."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    words = clean.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "…"
    return clean


def _synthesize_answer(question: str, top_citations: List[CitationItem], topics: List[str]) -> str:
    """
    Synthesize a coherent, concise answer directly from the top grounded citations.
    Zero hallucination guarantee: answers directly from retrieved video transcript evidence.
    """
    if not top_citations:
        topic_str = f" on {topics[0]}" if topics else ""
        return f"I couldn't find evidence addressing this question in the selected video transcripts{topic_str}."

    lead_snippet = top_citations[0].snippet.rstrip(".")
    secondary_points = [c.snippet.rstrip(".") for c in top_citations[1:3] if len(c.snippet) > 20]

    # Clean sentence capitalization
    if lead_snippet:
        lead_snippet = lead_snippet[0].upper() + lead_snippet[1:]

    parts = [f"According to the source video, {lead_snippet}."]
    if secondary_points:
        sec = secondary_points[0]
        if sec:
            sec = sec[0].upper() + sec[1:]
            parts.append(f"The speaker further highlights that {sec}.")

    return " ".join(parts)


@router.get("/{job_id}/suggestions", response_model=SuggestionsResponse)
async def get_chat_suggestions(
    job_id: str,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Return dynamic suggested starter questions for this specific video job.
    """
    db = await get_database()
    job = await db["jobs"].find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    topics = []
    fusion_meta = job.get("fusion_metadata") or {}
    if isinstance(fusion_meta, dict) and fusion_meta.get("topics_found"):
        topics = [t for t in fusion_meta.get("topics_found", []) if isinstance(t, str)]

    if not topics and job.get("concepts"):
        for c in job.get("concepts", []):
            if isinstance(c, dict) and c.get("name"):
                topics.append(c["name"])

    default_topic = topics[0] if topics else "this topic"
    second_topic = topics[1] if len(topics) > 1 else "key concepts"

    suggestions = [
        f"What is the main takeaway regarding {default_topic}?",
        f"How does the video explain {second_topic}?",
        "Where are the key formulas or practical examples explained?",
        "What are the main differences between the viewpoints discussed?",
    ]

    return SuggestionsResponse(job_id=job_id, suggestions=suggestions)


@router.post("/{job_id}/ask", response_model=ChatQueryResponse)
async def ask_job_question(
    job_id: str,
    payload: ChatQueryRequest,
    current_user: Optional[dict] = Depends(get_current_user_optional),
):
    """
    Interactive Q&A: Semantically search video transcripts using SBERT embeddings
    and return an answer with exact, clickable timestamp citations.
    """
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    db = await get_database()
    job = await db["jobs"].find_one({"job_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # 1. Gather all candidate segments from the job
    segments_to_search = []
    video_ids = job.get("video_ids", [])

    # Prefer highlight_segments already selected and stored on job
    for seg in job.get("highlight_segments", []):
        text = (seg.get("text") or "").strip()
        if len(text.split()) >= 5:
            segments_to_search.append({
                "video_id": seg.get("video_id", video_ids[0] if video_ids else ""),
                "start_time": float(seg.get("start_time", 0.0)),
                "end_time": float(seg.get("end_time", 0.0)),
                "text": text,
            })

    # If segments are empty, fallback to fetching transcripts from cache
    if not segments_to_search and video_ids:
        from .merge import fetch_transcripts_with_segments
        try:
            _, seg_map = await fetch_transcripts_with_segments(video_ids, allow_whisper=False)
            for vid, segs in seg_map.items():
                for s in segs:
                    stext = (s.get("text") or "").strip()
                    if len(stext.split()) >= 5:
                        start = float(s.get("start", s.get("start_time", 0.0)))
                        dur = float(s.get("duration", 0.0))
                        segments_to_search.append({
                            "video_id": vid,
                            "start_time": start,
                            "end_time": start + dur,
                            "text": stext,
                        })
        except Exception:
            pass

    if not segments_to_search:
        return ChatQueryResponse(
            job_id=job_id,
            question=question,
            answer="Transcript segments are not available for this job to perform Q&A.",
            citations=[],
            found=False,
            confidence="none",
        )

    # 2. Vector encoding via Sentence-BERT
    embedder = get_sentence_transformer()

    # Check LRU cache for segments matrix
    cached = _JOB_EMBEDDINGS_CACHE.get(job_id)
    if cached and cached.get("count") == len(segments_to_search):
        seg_vectors = cached["vectors"]
    else:
        texts = [s["text"] for s in segments_to_search]
        seg_vectors = await asyncio.to_thread(
            embedder.encode,
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        _JOB_EMBEDDINGS_CACHE[job_id] = {
            "count": len(segments_to_search),
            "vectors": seg_vectors,
        }

    # Encode query
    q_vec = await asyncio.to_thread(
        embedder.encode,
        question,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    # 3. Dense Cosine Similarity Search
    scores = np.dot(seg_vectors, q_vec)
    ranked_indices = np.argsort(scores)[::-1]

    # Map video IDs to readable channel / title if known
    video_titles: Dict[str, str] = {}
    rights_snap = job.get("rights_snapshot") or {}
    for vid, r_data in rights_snap.items():
        if isinstance(r_data, dict) and r_data.get("channel_title"):
            video_titles[vid] = r_data["channel_title"]

    citations: List[CitationItem] = []
    top_score = float(scores[ranked_indices[0]]) if len(ranked_indices) > 0 else 0.0

    # Minimum relevance threshold (BGE embeddings baseline for unrelated text is ~0.40-0.45)
    RELEVANCE_THRESHOLD = 0.50
    if top_score >= RELEVANCE_THRESHOLD:
        for idx in ranked_indices[:3]:
            score = float(scores[idx])
            if score < RELEVANCE_THRESHOLD:
                continue
            seg = segments_to_search[idx]
            vid = seg["video_id"]
            title = video_titles.get(vid, f"Video {vid[:6]}")
            citations.append(CitationItem(
                video_id=vid,
                video_title=title,
                timestamp_seconds=round(seg["start_time"], 2),
                timestamp_label=_format_timestamp(seg["start_time"]),
                snippet=_clean_snippet(seg["text"]),
                score=round(score, 3),
            ))

    # Determine confidence level
    if top_score >= 0.65:
        confidence = "high"
    elif top_score >= 0.50:
        confidence = "medium"
    else:
        confidence = "none"

    topics = job.get("fusion_metadata", {}).get("topics_found") or []
    answer = _synthesize_answer(question, citations, topics)

    return ChatQueryResponse(
        job_id=job_id,
        question=question,
        answer=answer,
        citations=citations,
        found=bool(citations),
        confidence=confidence,
    )
