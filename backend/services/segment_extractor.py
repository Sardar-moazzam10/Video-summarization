"""
Segment Extractor — Maps summary text to transcript timestamps.

Pipeline:
    1. Receive summary text + list of transcript segments (with timestamps)
    2. Group raw 1-3s entries into coherent ~40-word blocks
    3. Score each block using research paper-aligned 4-signal hybrid method:
       - SBERT semantic similarity to summary: 30%
       - TF-IDF extractive importance: 15%
       - CLIP cross-modal visual-text score: 35%
       - PGL-SUM temporal attention score: 20%
       Falls back to 70/30 SBERT/TF-IDF when CLIP/temporal are unavailable.
    4. Select top-scoring non-overlapping segments within time budget
    5. Return segments formatted for the existing /api/v1/merge endpoint

Reuses get_sentence_transformer() from fusion_engine.py — no second model load.
"""

import re
import numpy as np
from typing import List, Dict, Optional
from dataclasses import dataclass


# Research paper-aligned 4-signal weights (SBERT + TF-IDF + CLIP + temporal attention)
SEMANTIC_WEIGHT  = 0.30   # SBERT similarity to summary
TFIDF_WEIGHT     = 0.15   # TF-IDF extractive importance
CLIP_WEIGHT      = 0.35   # CLIP cross-modal visual-text score
TEMPORAL_WEIGHT  = 0.20   # PGL-SUM self-attention temporal importance

# Fallback weights when CLIP/temporal scores are absent (sums to 1.0)
FALLBACK_SEMANTIC_WEIGHT = 0.70
FALLBACK_TFIDF_WEIGHT    = 0.30


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
    visual_keyframes: Optional[List[Dict]] = None,
) -> List[Dict]:
    """
    Main entry point. Maps a summary to transcript timestamps.

    Args:
        video_id: YouTube video ID (passed through to output)
        transcript_segments: [{text, start, duration}] from MongoDB
        summary_text: Abstractive summary text (BART or Ollama output)
        target_duration_seconds: Total compiled video duration budget
        context_padding_seconds: Extra seconds added before/after each cut
        min_segment_duration: Skip segments shorter than this
        max_segment_duration: Cap any single segment at this length
        visual_keyframes: Optional [{timestamp, visual_score, ...}] from
            visual_keyframe_extractor.extract_keyframes(). When supplied,
            the per-segment visual score (max keyframe score whose timestamp
            falls inside the segment) is blended into the importance score.

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
        visual_keyframes=visual_keyframes,
    )

    selected = _select_within_budget(
        scored_segments=scored,
        target_seconds=target_duration_seconds,
        context_padding=context_padding_seconds,
    )

    return _format_for_merge(
        selected_segments=selected,
        video_id=video_id,
        context_padding=context_padding_seconds,
    )


def group_transcript_segments(
    raw_segments: List[Dict],
    max_segment_duration: float = 45.0,
    min_segment_duration: float = 5.0,
    words_per_group: int = 40,
) -> List[Dict]:
    """Public wrapper — returns grouped segments as plain dicts with start_time/end_time."""
    groups = _group_transcript_segments(raw_segments, max_segment_duration, min_segment_duration, words_per_group)
    return [{"start_time": g.start_time, "end_time": g.end_time, "text": g.text} for g in groups]


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
    visual_keyframes: Optional[List[Dict]] = None,
) -> List[ScoredSegment]:
    """
    Scores each grouped segment using research paper-aligned 4-signal blend:
      - SBERT semantic similarity (30%)
      - TF-IDF extractive importance (15%)
      - CLIP cross-modal visual-text score (35%)
      - PGL-SUM temporal attention score (20%)

    Degrades gracefully: if CLIP/temporal scores are absent from keyframes,
    falls back to 70/30 SBERT/TF-IDF weights.
    """
    segment_texts = [s.text for s in grouped_segments]

    tfidf_scores = _compute_tfidf_scores(segment_texts)
    semantic_scores = _compute_semantic_scores(
        segment_texts=segment_texts,
        summary_text=summary_text,
    )

    use_clip = bool(visual_keyframes) and any("clip_score" in kf for kf in visual_keyframes)
    use_temporal = bool(visual_keyframes) and any("temporal_score" in kf for kf in visual_keyframes)

    if use_clip or use_temporal:
        # Determine available signals and normalize weights to sum to 1.0
        sem_w     = SEMANTIC_WEIGHT
        tfidf_w   = TFIDF_WEIGHT
        clip_w    = CLIP_WEIGHT    if use_clip     else 0.0
        temp_w    = TEMPORAL_WEIGHT if use_temporal else 0.0

        total = sem_w + tfidf_w + clip_w + temp_w
        sem_w /= total; tfidf_w /= total; clip_w /= total; temp_w /= total

        for i, seg in enumerate(grouped_segments):
            sem    = semantic_scores[i]
            tfidf  = tfidf_scores[i]
            clip   = _clip_score_for_segment(seg.start_time, seg.end_time, visual_keyframes) if use_clip else 0.0
            temp   = _temporal_score_for_segment(seg.start_time, seg.end_time, visual_keyframes) if use_temporal else 0.0

            seg.importance_score = (sem_w * sem) + (tfidf_w * tfidf) + (clip_w * clip) + (temp_w * temp)
            seg.reason = (
                f"Semantic: {sem:.2f}, TF-IDF: {tfidf:.2f}, "
                f"CLIP: {clip:.2f}, Temporal: {temp:.2f}"
            )
    else:
        # Pure text fallback (70/30 SBERT/TF-IDF)
        for i, seg in enumerate(grouped_segments):
            sem   = semantic_scores[i]
            tfidf = tfidf_scores[i]
            seg.importance_score = (FALLBACK_SEMANTIC_WEIGHT * sem) + (FALLBACK_TFIDF_WEIGHT * tfidf)
            seg.reason = f"Semantic: {sem:.2f}, TF-IDF: {tfidf:.2f}"

    return grouped_segments


def _clip_score_for_segment(
    start_time: float,
    end_time: float,
    keyframes: List[Dict],
) -> float:
    """Max clip_score of any keyframe whose timestamp falls in [start_time, end_time]."""
    best = 0.0
    for kf in keyframes:
        ts = kf.get("timestamp", -1.0)
        if start_time <= ts <= end_time:
            score = kf.get("clip_score", 0.0)
            if score > best:
                best = score
    return best


def _temporal_score_for_segment(
    start_time: float,
    end_time: float,
    keyframes: List[Dict],
) -> float:
    """Max temporal_score of any keyframe whose timestamp falls in [start_time, end_time]."""
    best = 0.0
    for kf in keyframes:
        ts = kf.get("timestamp", -1.0)
        if start_time <= ts <= end_time:
            score = kf.get("temporal_score", 0.0)
            if score > best:
                best = score
    return best


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
    context_padding: float = 2.0,
) -> List[ScoredSegment]:
    """
    Greedy selection of top-scoring non-overlapping segments within budget.
    Accounts for context_padding that will be added by _format_for_merge so the
    final video does not exceed target_seconds.
    """
    candidates = sorted(
        scored_segments,
        key=lambda s: s.importance_score,
        reverse=True,
    )

    selected = []
    total_duration = 0.0

    for candidate in candidates:
        content_dur = candidate.end_time - candidate.start_time
        if content_dur <= 0:
            continue

        # Include padding in the budget accounting so the final video
        # matches target_seconds after _format_for_merge adds padding.
        padded_dur = content_dur + 2 * context_padding

        overlaps = any(
            not (
                candidate.end_time + overlap_gap_seconds <= sel.start_time
                or candidate.start_time >= sel.end_time + overlap_gap_seconds
            )
            for sel in selected
        )

        if overlaps:
            continue

        if total_duration + padded_dur <= target_seconds:
            selected.append(candidate)
            total_duration += padded_dur

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
            "text": seg.text,   # needed for narration-sync reordering
        }
        for seg in selected_segments
    ]


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences of at least 5 words."""
    raw = re.split(r'(?<=[.!?])\s+', text.strip())
    return [s.strip() for s in raw if len(s.split()) >= 5]


# ─── Narration-Driven Selection ────────────────────────────────────────────────

def extract_highlights_narration_driven(
    video_id: str,
    transcript_segments: List[Dict],
    srt_sentences: List[Dict],
    context_padding_seconds: float = 1.5,
    min_segment_duration: float = 3.0,
    max_segment_duration: float = 60.0,
    target_duration_seconds: int = 120,
) -> List[Dict]:
    """
    Narration-driven clip selection.

    Instead of scoring all segments and reordering later, each narration
    sentence directly votes for its best-matching transcript segment via SBERT.
    This guarantees every clip shown is thematically aligned with what is
    being said at that moment.

    Steps:
      1. Group SRT sentences into N buckets (N = clips that fit the time budget)
      2. SBERT-embed every bucket + every transcript group
      3. For each bucket, pick the highest-similarity transcript segment
      4. Deduplicate (same segment can win multiple buckets → keep once)
      5. Return clips ordered by narration position, not by timestamp

    Returns:
        List of segment dicts ready for generate_highlight_reel(),
        ordered so clip[i] plays while sentence bucket[i] is being narrated.
    """
    if not transcript_segments or not srt_sentences:
        return []

    grouped = _group_transcript_segments(
        transcript_segments, max_segment_duration, min_segment_duration
    )
    if not grouped:
        return []

    try:
        from .fusion_engine import get_sentence_transformer
        model = get_sentence_transformer()
    except Exception as e:
        print(f"[NarrationDriven] SBERT unavailable ({e}) — skipping")
        return []

    # How many clips fit within the time budget?
    avg_clip_seconds = 15.0  # conservative estimate for 1 clip with padding
    n_clips = max(2, int(target_duration_seconds / avg_clip_seconds))

    # Group SRT sentences into n_clips buckets so we get exactly that many clips
    narr_texts = [s["text"] for s in srt_sentences]
    bucket_size = max(1, len(narr_texts) // n_clips)
    buckets: List[str] = []
    for i in range(0, len(narr_texts), bucket_size):
        buckets.append(" ".join(narr_texts[i: i + bucket_size]))
    buckets = buckets[:n_clips]  # trim to n_clips groups

    seg_texts = [g.text for g in grouped]

    all_embs = model.encode(
        buckets + seg_texts, show_progress_bar=False, batch_size=32
    )
    bucket_embs = all_embs[: len(buckets)]
    seg_embs = all_embs[len(buckets):]

    def _norm(v: np.ndarray) -> np.ndarray:
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.where(n < 1e-9, 1e-9, n)

    sim = _norm(bucket_embs) @ _norm(seg_embs).T  # [n_buckets, n_segs]

    # Greedy assignment: each bucket claims its best segment (no repeats)
    used: set = set()
    result: List[Dict] = []

    for bucket_idx in range(len(buckets)):
        row = sim[bucket_idx].copy()
        for used_idx in used:
            row[used_idx] = -2.0
        best_seg_idx = int(np.argmax(row))
        score = float(sim[bucket_idx, best_seg_idx])

        if best_seg_idx not in used:
            used.add(best_seg_idx)
            seg = grouped[best_seg_idx]
            dur = seg.end_time - seg.start_time
            if dur >= min_segment_duration:
                result.append({
                    "video_id": video_id,
                    "start_time": max(0.0, seg.start_time - context_padding_seconds),
                    "end_time": seg.end_time + context_padding_seconds,
                    "importance_score": round(score, 4),
                    "reason": f"Narration-matched bucket {bucket_idx} (score={score:.2f})",
                    "text": seg.text,
                })

    print(
        f"[NarrationDriven] {video_id}: {len(buckets)} narration buckets "
        f"→ {len(result)} unique clips selected"
    )
    return result  # already in narration order — no reorder step needed


# ─── Narration-Sync ────────────────────────────────────────────────────────────

def reorder_clips_for_narration(
    clips: List[Dict],
    srt_content: str,
) -> List[Dict]:
    """
    Reorder video clips so they visually match the TTS narration sentence order.

    Problem without this:
      Narrator says "lion hunts at dusk" while showing an elephant clip — wrong.

    How it works:
      1. Parse SRT → list of narration sentences
      2. Embed each sentence + each clip's transcript text with SBERT
      3. Greedy assignment: for each narration sentence (in order), pick the
         clip whose text is most semantically similar to that sentence
      4. Return clips in that narration-matched order

    Result: when the narrator mentions lions, a lion-related clip plays.
    Not frame-perfect, but the right TOPIC plays at the right MOMENT.
    """
    if len(clips) < 2 or not srt_content.strip():
        return clips

    sentences = _parse_srt_sentences(srt_content)
    if not sentences:
        return clips

    clip_texts = [c.get("text", "") for c in clips]
    sentence_texts = [s["text"] for s in sentences]

    # Group sentences into N buckets matching the number of clips.
    # This prevents the case where 30 short sentences map to only 5 clips.
    n_clips = len(clips)
    chunk_size = max(1, len(sentence_texts) // n_clips)
    grouped_sentences: List[str] = []
    for i in range(0, len(sentence_texts), chunk_size):
        chunk = sentence_texts[i: i + chunk_size]
        grouped_sentences.append(" ".join(chunk))
    # Trim to n_clips groups so we have a 1:1 mapping
    grouped_sentences = grouped_sentences[:n_clips]

    try:
        from .fusion_engine import get_sentence_transformer
        model = get_sentence_transformer()

        all_texts = grouped_sentences + clip_texts
        all_embs = model.encode(all_texts, show_progress_bar=False, batch_size=32)

        sent_embs = all_embs[:len(grouped_sentences)]
        clip_embs = all_embs[len(grouped_sentences):]

        # L2-normalize
        def _norm(v: np.ndarray) -> np.ndarray:
            n = np.linalg.norm(v, axis=1, keepdims=True)
            return v / np.where(n < 1e-9, 1e-9, n)

        sim = _norm(sent_embs) @ _norm(clip_embs).T  # [S, C]

        # Greedy assignment: each narration group gets its best matching clip
        used: set = set()
        ordered: List[Dict] = []
        for sent_idx in range(len(grouped_sentences)):
            row = sim[sent_idx].copy()
            for used_idx in used:
                row[used_idx] = -2.0   # block already-assigned clips
            best = int(np.argmax(row))
            used.add(best)
            ordered.append(clips[best])

        # Append any clips not matched (extra clips after all sentences covered)
        for i, clip in enumerate(clips):
            if i not in used:
                ordered.append(clip)

        print(f"[Sync] Reordered {len(ordered)} clips to match narration sentence order")
        return ordered

    except Exception as e:
        print(f"[Sync] Narration reorder failed ({e}), keeping original order")
        return clips


def _parse_srt_sentences(srt_content: str) -> List[Dict]:
    """Parse SRT subtitle content into [{text, start_s, end_s}]."""
    blocks = re.split(r'\n\n+', srt_content.strip())
    results = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            # line 0: index, line 1: timestamps, line 2+: text
            ts_line = lines[1]
            start_str, end_str = ts_line.split("-->")

            def _ts(s: str) -> float:
                s = s.strip().replace(",", ".")
                h, m, rest = s.split(":")
                return int(h) * 3600 + int(m) * 60 + float(rest)

            results.append({
                "start_s": _ts(start_str),
                "end_s": _ts(end_str),
                "text": " ".join(lines[2:]).strip(),
            })
        except Exception:
            continue
    return results
