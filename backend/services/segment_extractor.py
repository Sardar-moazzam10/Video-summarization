"""
Segment Extractor — Maps summary text to transcript timestamps.

Pipeline:
    1. Receive summary text + list of transcript segments (with timestamps)
    2. Group raw 1-3s entries into coherent ~40-word blocks
    3. Score each block using hybrid method:
       - Semantic similarity (Sentence-BERT): 70% weight
       - TF-IDF extractive importance: 30% weight
    4. Select top-scoring non-overlapping segments within time budget
    5. Return segments formatted for the existing /api/v1/merge endpoint

Reuses get_sentence_transformer() from fusion_engine.py — no second model load.
"""

import re
import numpy as np
from typing import List, Dict
from dataclasses import dataclass


@dataclass
class ScoredSegment:
    video_id: str
    start_time: float
    end_time: float
    text: str
    importance_score: float = 0.0
    reason: str = ""


def extract_highlight_segments(
    video_id: str,
    transcript_segments: List[Dict],
    summary_text: str,
    target_duration_seconds: int = 120,
    context_padding_seconds: float = 3.0,
    min_segment_duration: float = 5.0,
    max_segment_duration: float = 45.0,
) -> List[Dict]:
    """
    Main entry point. Maps a summary to transcript timestamps.

    Args:
        video_id: YouTube video ID (passed through to output)
        transcript_segments: [{text, start, duration}] from MongoDB
        summary_text: Abstractive summary text (BART or Gemini output)
        target_duration_seconds: Total compiled video duration budget
        context_padding_seconds: Extra seconds added before/after each cut
        min_segment_duration: Skip segments shorter than this
        max_segment_duration: Cap any single segment at this length

    Returns:
        List of segment dicts for /api/v1/merge:
        [{video_id, start_time, end_time, importance_score, reason}]
    """
    if not transcript_segments or not isinstance(transcript_segments, list):
        return []

    grouped = _group_transcript_segments(
        transcript_segments,
        max_segment_duration=max_segment_duration,
        min_segment_duration=min_segment_duration,
    )

    if not grouped:
        return []

    scored = _score_segments_hybrid(
        grouped_segments=grouped,
        summary_text=summary_text,
    )

    selected = _select_within_budget(
        scored_segments=scored,
        target_seconds=target_duration_seconds,
    )

    return _format_for_merge(
        selected_segments=selected,
        video_id=video_id,
        context_padding=context_padding_seconds,
    )


def _group_transcript_segments(
    raw_segments: List[Dict],
    max_segment_duration: float,
    min_segment_duration: float,
    words_per_group: int = 40,
) -> List[ScoredSegment]:
    """
    Groups individual transcript entries into larger coherent blocks.

    Individual entries are often 1-3 seconds. We group them into
    ~40-word blocks (15-40s) which are meaningful as video clips.
    Natural 2-second silence gaps are used as topic boundaries.
    """
    groups = []
    buffer_text = []
    buffer_start = None
    buffer_end = None
    prev_end = None

    for seg in raw_segments:
        text = seg.get("text", "").strip()
        if not text:
            continue

        start = float(seg.get("start", 0))
        duration = float(seg.get("duration", 0))
        end = start + duration

        natural_pause = prev_end is not None and (start - prev_end) > 2.0
        word_limit_reached = len(" ".join(buffer_text).split()) >= words_per_group

        if buffer_text and (natural_pause or word_limit_reached):
            group_duration = buffer_end - buffer_start
            if group_duration >= min_segment_duration:
                groups.append(ScoredSegment(
                    video_id="",
                    start_time=buffer_start,
                    end_time=min(buffer_end, buffer_start + max_segment_duration),
                    text=" ".join(buffer_text),
                ))
            buffer_text = []
            buffer_start = None

        if buffer_start is None:
            buffer_start = start
        buffer_text.append(text)
        buffer_end = end
        prev_end = end

    if buffer_text and buffer_start is not None:
        group_duration = buffer_end - buffer_start
        if group_duration >= min_segment_duration:
            groups.append(ScoredSegment(
                video_id="",
                start_time=buffer_start,
                end_time=min(buffer_end, buffer_start + max_segment_duration),
                text=" ".join(buffer_text),
            ))

    return groups


def _score_segments_hybrid(
    grouped_segments: List[ScoredSegment],
    summary_text: str,
    semantic_weight: float = 0.7,
    tfidf_weight: float = 0.3,
) -> List[ScoredSegment]:
    """
    Scores each grouped segment using combined semantic + TF-IDF method.

    Combined formula: (0.7 × semantic_similarity) + (0.3 × tfidf_importance)
    """
    segment_texts = [s.text for s in grouped_segments]

    tfidf_scores = _compute_tfidf_scores(segment_texts)
    semantic_scores = _compute_semantic_scores(
        segment_texts=segment_texts,
        summary_text=summary_text,
    )

    for i, seg in enumerate(grouped_segments):
        sem = semantic_scores[i]
        tfidf = tfidf_scores[i]
        seg.importance_score = (semantic_weight * sem) + (tfidf_weight * tfidf)
        seg.reason = f"Semantic match: {sem:.2f}, TF-IDF: {tfidf:.2f}"

    return grouped_segments


def _compute_tfidf_scores(segment_texts: List[str]) -> List[float]:
    """
    Score each segment by TF-IDF importance (extractive approach).
    Returns normalized list of floats in [0, 1].
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    if len(segment_texts) < 2:
        return [1.0] * len(segment_texts)

    vectorizer = TfidfVectorizer(
        stop_words="english",
        max_features=500,
        ngram_range=(1, 2),
    )
    try:
        tfidf_matrix = vectorizer.fit_transform(segment_texts)
        scores = np.asarray(tfidf_matrix.sum(axis=1)).flatten()
        max_score = scores.max()
        if max_score > 0:
            scores = scores / max_score
        return scores.tolist()
    except Exception:
        return [0.5] * len(segment_texts)


def _compute_semantic_scores(
    segment_texts: List[str],
    summary_text: str,
) -> List[float]:
    """
    For each transcript segment, compute max cosine similarity to any
    summary sentence using Sentence-BERT.

    Reuses get_sentence_transformer() singleton — no extra memory load.
    If summary_text is empty, returns [0.5] * n (TF-IDF takes over).
    """
    summary_sentences = _split_sentences(summary_text)
    if not summary_sentences:
        return [0.5] * len(segment_texts)

    try:
        from .fusion_engine import get_sentence_transformer
        model = get_sentence_transformer()
    except Exception:
        return [0.5] * len(segment_texts)

    all_texts = summary_sentences + segment_texts
    all_embeddings = model.encode(all_texts, show_progress_bar=False)

    n_summary = len(summary_sentences)
    summary_embeddings = all_embeddings[:n_summary]
    segment_embeddings = all_embeddings[n_summary:]

    def _normalize(vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1e-9, norms)
        return vectors / norms

    seg_norm = _normalize(segment_embeddings)
    sum_norm = _normalize(summary_embeddings)

    similarity_matrix = np.dot(seg_norm, sum_norm.T)
    max_similarities = similarity_matrix.max(axis=1)

    min_sim = max_similarities.min()
    max_sim = max_similarities.max()
    if max_sim > min_sim:
        normalized = (max_similarities - min_sim) / (max_sim - min_sim)
    else:
        normalized = np.ones_like(max_similarities) * 0.5

    return normalized.tolist()


def _select_within_budget(
    scored_segments: List[ScoredSegment],
    target_seconds: int,
    overlap_gap_seconds: float = 5.0,
) -> List[ScoredSegment]:
    """
    Greedy selection of top-scoring non-overlapping segments within budget.
    Allows 10% overage on target duration.
    """
    candidates = sorted(
        scored_segments,
        key=lambda s: s.importance_score,
        reverse=True,
    )

    selected = []
    total_duration = 0.0

    for candidate in candidates:
        duration = candidate.end_time - candidate.start_time
        if duration <= 0:
            continue

        overlaps = any(
            not (
                candidate.end_time + overlap_gap_seconds <= sel.start_time
                or candidate.start_time >= sel.end_time + overlap_gap_seconds
            )
            for sel in selected
        )

        if overlaps:
            continue

        if total_duration + duration <= target_seconds * 1.1:
            selected.append(candidate)
            total_duration += duration

        if total_duration >= target_seconds:
            break

    selected.sort(key=lambda s: s.start_time)
    return selected


def _format_for_merge(
    selected_segments: List[ScoredSegment],
    video_id: str,
    context_padding: float,
) -> List[Dict]:
    """
    Formats segments as dicts expected by /api/v1/merge.
    Adds context padding (±seconds) and sets video_id.
    """
    return [
        {
            "video_id": video_id,
            "start_time": max(0.0, seg.start_time - context_padding),
            "end_time": seg.end_time + context_padding,
            "importance_score": round(seg.importance_score, 4),
            "reason": seg.reason,
        }
        for seg in selected_segments
    ]


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences of at least 5 words."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if len(s.split()) >= 5]
