"""
Semantic Segmenter — turns a raw timestamped transcript into COMPLETE THOUGHTS.

Why this exists
---------------
The old selection unit was a ~40-word / 20-second block produced by
segment_extractor._group_transcript_segments(). That function decides where to
cut from word count and elapsed time, with only a *soft* preference for a
sentence ending (capped at 1.6x the duration floor). On an auto-caption
transcript with no punctuation the preference never fires at all, so a clip
routinely begins in the middle of an explanation:

    00:25  "...and that's why it overfits."      <- clip starts here
    00:40  "So you regularise."                  <- clip ends here

The viewer experiences that as the video starting mid-thought.

This module introduces the layer the pipeline was missing:

    caption entries  ->  SENTENCES  ->  SEMANTIC SEGMENTS

A semantic segment is a run of consecutive sentences that discuss one thing.
Boundaries are derived, never hardcoded, using a TextTiling-style depth score
over SBERT sentence embeddings: for every candidate gap we compare the block of
sentences before it against the block after it, and a gap whose similarity is a
local minimum (a "valley") is a topic shift.

Everything degrades gracefully. No punctuation -> pause-and-length sentence
reconstruction. No SBERT -> fixed-width segmentation on sentence boundaries. No
timestamps -> empty list, and the caller falls back to the legacy path.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np


# Sentence terminators. The Devanagari danda is kept because the transcript
# service translates non-English sources and mixed output does occur.
_SENTENCE_ENDINGS = (".", "!", "?", "।")

# A silence longer than this between caption entries is treated as a sentence
# break when punctuation is unavailable.
_PAUSE_SECONDS = 1.2

# Strictness of the topic-boundary test, in standard deviations above the mean
# depth of this transcript. 0.0 cuts at every above-average valley; higher values
# demand a more decisive topic change and therefore preserve longer, complete
# explanations. Chosen by measuring how many sustained explanations survive
# intact — see _choose_boundaries.
BOUNDARY_DEPTH_K = 0.5


# When a transcript carries no punctuation at all, sentences are reconstructed
# at roughly this many words (a typical spoken sentence).
_FALLBACK_SENTENCE_WORDS = 22

# Fraction of caption entries that must end in punctuation before we trust it.
_PUNCTUATION_TRUST_RATIO = 0.10


@dataclass
class Sentence:
    """One reconstructed spoken sentence with its own time span."""
    text: str
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass
class SemanticSegment:
    """
    A complete thought: consecutive sentences on one topic.

    This is the unit the optimizer selects and ffmpeg cuts. It always begins at
    a sentence start and ends at a sentence end, so a clip can never open or
    close mid-sentence.
    """
    video_id: str
    start_time: float
    end_time: float
    text: str
    sentences: List[Sentence] = field(default_factory=list)
    # Filled in by downstream stages
    embedding: Optional[np.ndarray] = None
    concept_scores: Dict[str, float] = field(default_factory=dict)
    boundary_confidence: float = 0.0   # how clean the topic break was, 0..1
    completeness: float = 1.0          # 1.0 = starts and ends on a sentence

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def to_dict(self) -> Dict:
        return {
            "video_id": self.video_id,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
            "text": self.text,
            "duration": round(self.duration, 2),
            "boundary_confidence": round(self.boundary_confidence, 4),
            "completeness": round(self.completeness, 4),
        }


# =====================================================================
# STEP 1 — caption entries  ->  sentences
# =====================================================================

def build_sentences(raw_segments: Sequence[Dict]) -> List[Sentence]:
    """
    Reconstruct sentences from raw transcript entries.

    Caption entries run 1-5 seconds and are cut for *display width*, not for
    meaning, so they routinely split a sentence across three entries. This puts
    them back together.

    Two strategies, chosen by inspecting the data rather than by configuration:

      * Punctuated transcripts (YouTube API, Whisper) -> split on terminators.
      * Unpunctuated transcripts (many auto-captions) -> split on pauses longer
        than _PAUSE_SECONDS, with a word-count ceiling so a monologue without
        pauses still yields bounded sentences.

    Entries with no usable timestamp are skipped rather than defaulted to 0,
    because a run of entries all claiming t=0 would collapse the timeline.
    """
    entries: List[Dict] = []
    for seg in raw_segments or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start", seg.get("start_time"))
        if start is None:
            continue
        try:
            start = float(start)
        except (TypeError, ValueError):
            continue
        dur = seg.get("duration")
        if dur is None:
            end = seg.get("end", seg.get("end_time"))
            try:
                dur = float(end) - start if end is not None else 0.0
            except (TypeError, ValueError):
                dur = 0.0
        try:
            dur = max(0.0, float(dur))
        except (TypeError, ValueError):
            dur = 0.0
        # Caption text is often hard-wrapped; newlines are not meaningful.
        entries.append({"text": " ".join(text.split()), "start": start, "end": start + dur})

    if not entries:
        return []

    entries.sort(key=lambda e: e["start"])

    punctuated = sum(1 for e in entries if e["text"].endswith(_SENTENCE_ENDINGS))
    trust_punctuation = (punctuated / len(entries)) >= _PUNCTUATION_TRUST_RATIO

    sentences: List[Sentence] = []
    buf: List[str] = []
    buf_start: Optional[float] = None
    buf_end: Optional[float] = None
    prev_end: Optional[float] = None

    def flush() -> None:
        nonlocal buf, buf_start, buf_end
        if buf and buf_start is not None:
            text = " ".join(buf).strip()
            if text:
                sentences.append(Sentence(text=text, start=buf_start, end=max(buf_end, buf_start)))
        buf, buf_start, buf_end = [], None, None

    for entry in entries:
        # A real pause is a sentence break under either strategy. Caption entries
        # frequently overlap (negative gap), so this fires only on true silence.
        if (
            prev_end is not None
            and buf
            and (entry["start"] - prev_end) > _PAUSE_SECONDS
        ):
            flush()

        if buf_start is None:
            buf_start = entry["start"]
        buf.append(entry["text"])
        buf_end = entry["end"] if buf_end is None else max(buf_end, entry["end"])
        prev_end = entry["end"]

        if trust_punctuation:
            if entry["text"].endswith(_SENTENCE_ENDINGS):
                flush()
        else:
            if len(" ".join(buf).split()) >= _FALLBACK_SENTENCE_WORDS:
                flush()

    flush()

    # A punctuated transcript can still contain several sentences inside one
    # caption entry ("Right. So what is overfitting?"). Split those out, sharing
    # the entry's span proportionally to character length so timings stay sane.
    if trust_punctuation:
        sentences = _split_multi_sentence_spans(sentences)

    return [s for s in sentences if s.word_count > 0]


def _split_multi_sentence_spans(sentences: List[Sentence]) -> List[Sentence]:
    """Split any Sentence whose text contains multiple terminators."""
    out: List[Sentence] = []
    for sent in sentences:
        parts = [p.strip() for p in re.split(r'(?<=[.!?।])\s+', sent.text) if p.strip()]
        if len(parts) <= 1:
            out.append(sent)
            continue
        total_chars = sum(len(p) for p in parts) or 1
        cursor = sent.start
        for part in parts:
            share = (len(part) / total_chars) * sent.duration
            out.append(Sentence(text=part, start=cursor, end=cursor + share))
            cursor += share
        # Absorb float drift so the last piece ends exactly where the entry did.
        out[-1].end = sent.end
    return out


# =====================================================================
# STEP 2 — sentences  ->  semantic segments
# =====================================================================

def segment_semantically(
    sentences: List[Sentence],
    video_id: str = "",
    min_duration: float = 20.0,
    max_duration: float = 90.0,
    embedder=None,
    block_size: int = 3,
) -> List[SemanticSegment]:  # noqa: C901
    """
    Group sentences into complete-thought segments using TextTiling depth scores.

    For each gap between sentence i and i+1 we embed the `block_size` sentences
    on each side, take the cosine similarity of the two block centroids, and
    invert it into a "depth". Gaps that are local minima of similarity (i.e.
    local maxima of depth) are topic shifts.

    A boundary is only honoured if it leaves both the closing segment and the
    opening one above `min_duration`; a boundary is *forced* once a segment
    reaches `max_duration`, at the least-similar gap available, so a long
    monologue still splits somewhere meaningful rather than at an arbitrary
    word count.

    Args:
        sentences:    output of build_sentences()
        video_id:     stamped onto every produced segment
        min_duration: floor for a segment, in seconds
        max_duration: ceiling for a segment, in seconds
        embedder:     anything with .encode(list[str]) -> ndarray. Defaults to
                      the shared SBERT singleton. Pass a fake in tests.
        block_size:   sentences compared on each side of a candidate gap

    Returns:
        Segments in chronological order. Empty if there is nothing to segment.
    """
    if not sentences:
        return []

    if len(sentences) == 1:
        return [_make_segment(sentences, video_id, 1.0)]

    similarities, unit = _gap_similarities(
        sentences, embedder=embedder, block_size=block_size, return_vectors=True
    )
    boundaries = _choose_boundaries(sentences, similarities, min_duration, max_duration)

    segments: List[SemanticSegment] = []
    start_idx = 0
    for cut in boundaries + [len(sentences)]:
        if cut <= start_idx:
            continue
        block = sentences[start_idx:cut]
        # Depth at the gap that closed this block is how confident we are that
        # it really ended here; the final block has no closing gap.
        gap_idx = cut - 1
        confidence = 0.0
        if 0 <= gap_idx < len(similarities):
            confidence = float(np.clip(1.0 - similarities[gap_idx], 0.0, 1.0))
        block_vectors = unit[start_idx:cut] if unit is not None else None
        segments.append(_make_segment(block, video_id, confidence, block_vectors))
        start_idx = cut

    return _merge_undersized(segments, min_duration, max_duration)


def _make_segment(
    block: List[Sentence],
    video_id: str,
    confidence: float,
    block_vectors: Optional[np.ndarray] = None,
) -> SemanticSegment:
    # The segment embedding is the mean of its sentence embeddings, which were
    # already computed to find the boundaries. Encoding the joined text again
    # would be a second full pass of SBERT over the whole transcript — measured
    # at 277 seconds for a 75-minute video, so not a rounding error — for a
    # vector that means the same thing.
    embedding = None
    if block_vectors is not None and len(block_vectors):
        mean = block_vectors.mean(axis=0)
        norm = np.linalg.norm(mean)
        embedding = mean / norm if norm > 1e-9 else mean

    return SemanticSegment(
        video_id=video_id,
        start_time=block[0].start,
        end_time=block[-1].end,
        text=" ".join(s.text for s in block),
        sentences=list(block),
        boundary_confidence=confidence,
        completeness=1.0,   # by construction: whole sentences only
        embedding=embedding,
    )


def _gap_similarities(
    sentences: List[Sentence],
    embedder=None,
    block_size: int = 3,
    return_vectors: bool = False,
):
    """
    Cosine similarity across each of the n-1 sentence gaps.

    Returns an array of length len(sentences)-1 where index i is the similarity
    across the gap between sentence i and sentence i+1. On any failure this
    returns all-0.5, which makes every gap look equally uninteresting and hands
    control to the duration rules — a safe degradation, not a crash.

    With `return_vectors`, also hands back the L2-normalised sentence embeddings
    so the caller can build segment vectors from them instead of re-encoding.
    """
    n = len(sentences)
    neutral = np.full(max(n - 1, 0), 0.5, dtype=float)

    def _out(sims, vectors=None):
        return (sims, vectors) if return_vectors else sims

    if embedder is None:
        try:
            from .fusion_engine import get_sentence_transformer
            embedder = get_sentence_transformer()
        except Exception as exc:                                  # pragma: no cover
            print(f"[Segmenter] SBERT unavailable ({exc}) — using duration-only boundaries")
            return _out(neutral)

    try:
        embeddings = np.asarray(
            embedder.encode([s.text for s in sentences], show_progress_bar=False, batch_size=64)
        )
    except TypeError:
        # Fakes in tests take encode(texts) only.
        embeddings = np.asarray(embedder.encode([s.text for s in sentences]))
    except Exception as exc:                                      # pragma: no cover
        print(f"[Segmenter] Embedding failed ({exc}) — using duration-only boundaries")
        return _out(neutral)

    if embeddings.ndim != 2 or embeddings.shape[0] != n:
        return _out(neutral)

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / np.where(norms < 1e-9, 1e-9, norms)

    sims = np.empty(n - 1, dtype=float)
    for i in range(n - 1):
        left = unit[max(0, i - block_size + 1): i + 1].mean(axis=0)
        right = unit[i + 1: min(n, i + 1 + block_size)].mean(axis=0)
        denom = (np.linalg.norm(left) * np.linalg.norm(right)) or 1e-9
        sims[i] = float(np.dot(left, right) / denom)

    return _out(sims, unit)


def _depth_scores(similarities: np.ndarray) -> np.ndarray:
    """
    TextTiling depth: how far a gap falls below the peaks on either side of it.

    depth(i) = (left_peak - sim(i)) + (right_peak - sim(i))

    where each peak is found by walking outward from i while similarity keeps
    rising. This is the measurement that distinguishes a topic change from a
    pause for breath, and it is not the same question as "is this gap below
    average". Similarity dips constantly inside a sustained explanation — the
    speaker moves from stating a claim to giving an example — and roughly half
    of all gaps sit below the mean by definition, so a rule of
    "local minimum AND below mean" fires deep inside explanations.

    A shallow valley between two shallow peaks scores near zero: the topic never
    really left. A deep valley between two high peaks scores high: it did.
    """
    n = len(similarities)
    depths = np.zeros(n, dtype=float)
    for i in range(n):
        left = similarities[i]
        j = i - 1
        while j >= 0 and similarities[j] >= left:
            left = similarities[j]
            j -= 1
        right = similarities[i]
        k = i + 1
        while k < n and similarities[k] >= right:
            right = similarities[k]
            k += 1
        depths[i] = (left - similarities[i]) + (right - similarities[i])
    return depths


def _choose_boundaries(
    sentences: List[Sentence],
    similarities: np.ndarray,
    min_duration: float,
    max_duration: float,
) -> List[int]:
    """
    Pick cut indices. A cut at index k means a segment ends at sentence k-1.

    Two rules, applied left to right:
      1. Once the running segment is past `min_duration`, cut at a gap whose
         DEPTH clears the transcript's own depth threshold — a valley that is
         deep relative to the peaks around it, i.e. a genuine topic shift.
      2. If the running segment reaches `max_duration` without finding one, cut
         at the weakest gap seen since the floor was met. A forced cut at the
         least-connected point still beats a cut at an arbitrary one.

    Rule 1 previously read "local minimum AND below the mean similarity", which
    cut far too eagerly: validated against a 75-minute lecture, only 25% of
    sustained explanations survived intact, and the tumour-classification
    example running 44:17-45:39 was entered at 44:58 — dropping the setup
    sentence "if a new patient walks into your office" and starting the viewer
    mid-argument. That is the exact defect semantic segmentation exists to
    prevent.
    """
    if len(similarities) == 0:
        return []

    depths = _depth_scores(similarities)
    # Threshold from the transcript's own depth distribution, so a monotone
    # reader and an argumentative one are each judged on their own scale.
    threshold = float(depths.mean() + BOUNDARY_DEPTH_K * depths.std())
    boundaries: List[int] = []
    seg_start = 0

    def span(from_idx: int, to_idx: int) -> float:
        return sentences[to_idx].end - sentences[from_idx].start

    i = 0
    while i < len(similarities):
        elapsed = span(seg_start, i)

        if elapsed >= min_duration:
            prev_d = depths[i - 1] if i > 0 else -1.0
            next_d = depths[i + 1] if i + 1 < len(depths) else -1.0
            is_local_max = depths[i] >= prev_d and depths[i] >= next_d

            if is_local_max and depths[i] >= threshold:
                boundaries.append(i + 1)
                seg_start = i + 1
                i += 1
                continue

        if elapsed >= max_duration:
            # Forced cut: weakest gap in the window that still leaves a legal
            # segment behind. Searching from seg_start would allow a cut that
            # produces a sub-min_duration piece, so start where the floor is met.
            window_start = seg_start
            while window_start < i and span(seg_start, window_start) < min_duration:
                window_start += 1
            window = similarities[window_start: i + 1]
            cut_at = window_start + int(np.argmin(window)) if len(window) else i
            boundaries.append(cut_at + 1)
            seg_start = cut_at + 1
            i = cut_at + 1
            continue

        i += 1

    return boundaries


def _merge_undersized(
    segments: List[SemanticSegment],
    min_duration: float,
    max_duration: float,
) -> List[SemanticSegment]:
    """
    Fold a too-short segment into a neighbour instead of discarding it.

    Dropping short segments is what made the old grouper lose whole minutes of a
    video (one 14.7-minute source produced a single usable group). A trailing
    fragment is the tail of the thought before it, so that is where it goes —
    unless doing so would blow past max_duration, in which case it is kept as
    its own short segment rather than corrupting a good one.
    """
    if not segments:
        return []

    merged: List[SemanticSegment] = [segments[0]]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg.duration < min_duration and (seg.end_time - prev.start_time) <= max_duration:
            prev.end_time = seg.end_time
            prev.text = f"{prev.text} {seg.text}".strip()
            prev.sentences.extend(seg.sentences)
            prev.boundary_confidence = seg.boundary_confidence
        else:
            merged.append(seg)

    # A single leading fragment can survive the loop above when it is first.
    if len(merged) > 1 and merged[0].duration < min_duration:
        head, nxt = merged[0], merged[1]
        if (nxt.end_time - head.start_time) <= max_duration:
            nxt.start_time = head.start_time
            nxt.text = f"{head.text} {nxt.text}".strip()
            nxt.sentences = head.sentences + nxt.sentences
            merged.pop(0)

    return merged


# =====================================================================
# PUBLIC ENTRY POINT
# =====================================================================

# Segmentation is the expensive stage: it embeds every sentence of the
# transcript, measured at 61-69 seconds for a 75-minute lecture. The result
# depends only on the transcript and the two duration bounds — NOT on the user's
# chosen summary length — so the five duration modes of one video are five
# optimizer runs (0.08-0.23s each) over one analysis, not five analyses.
#
# Bounded to a handful of videos because each entry holds a 768-float vector per
# segment (~360 KB for a 75-minute source); an unbounded dict on a long-running
# server is a leak, not a cache.
_SEGMENT_CACHE: "OrderedDict[str, List[SemanticSegment]]" = OrderedDict()
_SEGMENT_CACHE_MAX = 8


def _segment_cache_key(raw_segments, video_id, min_duration, max_duration) -> str:
    digest = hashlib.sha1()
    digest.update(f"{video_id}|{min_duration}|{max_duration}|{len(raw_segments)}".encode())
    # Sampling rather than hashing every entry: a transcript that matches on
    # length, endpoints and an even sample is the same transcript, and hashing
    # 2000 entries on every call would eat into the saving being made.
    step = max(1, len(raw_segments) // 40)
    for seg in list(raw_segments)[::step]:
        digest.update(str(seg.get("text", ""))[:120].encode("utf-8", "ignore"))
        digest.update(str(seg.get("start", "")).encode())
    return digest.hexdigest()


def build_semantic_segments(
    raw_segments: Sequence[Dict],
    video_id: str = "",
    min_duration: float = 20.0,
    max_duration: float = 90.0,
    embedder=None,
    use_cache: bool = True,
) -> List[SemanticSegment]:
    """
    One call: raw transcript entries -> complete-thought segments.

    Returns [] when the transcript is unusable (no entries, no timestamps), which
    the caller treats as "fall back to the legacy grouper".

    Results are cached per (transcript, bounds) so that requesting a 5-, 10-,
    15-, 20- and 30-minute summary of the same video pays for segmentation once.
    Pass use_cache=False to force recomputation.
    """
    if not raw_segments:
        return []

    key = _segment_cache_key(raw_segments, video_id, min_duration, max_duration) if use_cache else None
    if key is not None and key in _SEGMENT_CACHE:
        _SEGMENT_CACHE.move_to_end(key)
        cached = _SEGMENT_CACHE[key]
        print(f"[Segmenter] Cache hit for {video_id or 'video'} "
              f"({len(cached)} segments) — skipping re-embedding")
        return cached

    sentences = build_sentences(raw_segments)
    if not sentences:
        return []
    segments = segment_semantically(
        sentences,
        video_id=video_id,
        min_duration=min_duration,
        max_duration=max_duration,
        embedder=embedder,
    )

    if key is not None and segments:
        _SEGMENT_CACHE[key] = segments
        _SEGMENT_CACHE.move_to_end(key)
        while len(_SEGMENT_CACHE) > _SEGMENT_CACHE_MAX:
            _SEGMENT_CACHE.popitem(last=False)

    return segments


def clear_segment_cache() -> None:
    """Drop the cached segmentations (used by tests)."""
    _SEGMENT_CACHE.clear()
