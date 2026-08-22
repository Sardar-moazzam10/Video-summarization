"""
Concept Extractor — finds the VIP ideas in a long transcript.

The problem this solves
-----------------------
Selection used to score every candidate clip by cosine similarity to ONE
abstractive summary. That makes the summary a bottleneck: a 1-hour ML podcast
compressed to 800 words mentions "overfitting" once, so every clip about
overfitting competes for the similarity mass of a single sentence, and whole
topics that the summary skipped can never win a slot.

Extracting concepts first inverts that. We ask what the video is *about* —
"Overfitting", "Feature Engineering", "Transformers" — score each concept's
importance, and then let candidate segments compete on how well they explain
those concepts. Nothing is hardcoded: the concepts come from the content, so
the same code works on a lecture, an interview, or a cooking tutorial.

Architecture (hierarchical — the whole transcript never goes to the LLM)
-----------------------------------------------------------------------
    1. chunk the timestamped transcript into overlapping time windows
    2. extract concepts per chunk with Ollama (JSON mode, one call per chunk)
    3. embed concept names with SBERT and cluster near-duplicates
       ("overfitting" / "over-fitting" / "model memorises the training set")
    4. rank globally: importance x how many chunks support it x spread
    5. keep the timestamps every mention came from

Fallbacks, in order:
    Ollama unavailable / times out  -> TF-IDF keyphrase extraction (no LLM)
    SBERT unavailable               -> string-normalised merging
    Nothing works                   -> empty list; the optimizer then runs on
                                       semantic relevance + coverage alone
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np


# Words per LLM chunk. llama3.2:3b has an 8k context; ~700 words of transcript
# plus the prompt leaves ample room for the JSON answer without truncation.
CHUNK_WORDS = 700

# Overlap between consecutive chunks. A concept introduced at the end of one
# chunk and explained at the start of the next would otherwise be seen in
# fragments by both calls and scored as weak in each.
CHUNK_OVERLAP_RATIO = 0.15

# Concept names closer than this in SBERT space are the same concept.
CONCEPT_MERGE_THRESHOLD = 0.72

# Hard ceiling on LLM calls for one video, so a 3-hour source cannot make the
# job run for an hour. Beyond this, chunks are sampled evenly across the
# timeline rather than truncated to the start — truncating would reintroduce
# exactly the beginning-bias this whole change exists to remove.
MAX_LLM_CHUNKS = 14


CONCEPT_PROMPT = """You are analysing part of a video transcript. Output ONLY valid JSON, no prose, no code fences.

Identify the most important CONCEPTS actually discussed in this excerpt. A concept is a topic, idea, technique, or claim the speaker explains or argues for — not a passing mention, not a filler phrase, not the speaker's name.

Return this exact shape:
{{"concepts": [{{"concept": "<2-4 word name>", "importance": <0.0-1.0>, "reason": "<why it matters, one short sentence>", "evidence": "<a short quote from the excerpt>"}}]}}

Rules:
- At most {max_concepts} concepts. Fewer is fine if the excerpt is thin.
- "importance" reflects how central the concept is to THIS excerpt.
- Use the excerpt's own vocabulary for the concept name.
- If the excerpt contains no real content (intro music, greetings, ads), return {{"concepts": []}}.

EXCERPT (from {start_label} to {end_label}):
{chunk_text}

JSON:"""


@dataclass
class Concept:
    """One important idea, merged across every chunk that mentioned it."""
    name: str
    importance: float = 0.0
    reason: str = ""
    evidence: List[str] = field(default_factory=list)
    # Time windows where this concept was discussed, as (start, end) seconds.
    timestamps: List[tuple] = field(default_factory=list)
    support: int = 1                      # how many chunks independently found it
    aliases: List[str] = field(default_factory=list)
    embedding: Optional[np.ndarray] = None
    source: str = "llm"                   # "llm" or "tfidf"

    def to_dict(self) -> Dict:
        return {
            "concept": self.name,
            "importance": round(float(self.importance), 4),
            "reason": self.reason,
            "evidence": self.evidence[:3],
            "timestamps": [[round(a, 1), round(b, 1)] for a, b in self.timestamps[:8]],
            "support": self.support,
            "aliases": self.aliases[:5],
            "source": self.source,
        }


@dataclass
class Chunk:
    """A time-bounded window of transcript text handed to the LLM."""
    text: str
    start: float
    end: float
    index: int


# =====================================================================
# CHUNKING
# =====================================================================

def build_chunks(
    segments: Sequence,
    chunk_words: int = CHUNK_WORDS,
    overlap_ratio: float = CHUNK_OVERLAP_RATIO,
) -> List[Chunk]:
    """
    Split timestamped units into overlapping word-budgeted chunks.

    `segments` may be SemanticSegment objects or plain dicts carrying
    start_time/end_time/text — both are accepted so this can run before or after
    semantic segmentation.
    """
    units: List[Dict] = []
    for seg in segments or []:
        if hasattr(seg, "start_time"):
            text, start, end = seg.text, seg.start_time, seg.end_time
        else:
            text = seg.get("text", "")
            start = seg.get("start_time", seg.get("start", 0.0))
            end = seg.get("end_time")
            if end is None:
                end = float(start) + float(seg.get("duration", 0.0))
        text = (text or "").strip()
        if text:
            units.append({"text": text, "start": float(start), "end": float(end)})

    if not units:
        return []

    step = max(1, int(chunk_words * (1.0 - overlap_ratio)))
    chunks: List[Chunk] = []
    cursor = 0
    idx = 0

    while cursor < len(units):
        taken: List[Dict] = []
        words = 0
        j = cursor
        while j < len(units) and words < chunk_words:
            taken.append(units[j])
            words += len(units[j]["text"].split())
            j += 1
        if not taken:
            break

        chunks.append(Chunk(
            text=" ".join(u["text"] for u in taken),
            start=taken[0]["start"],
            end=taken[-1]["end"],
            index=idx,
        ))
        idx += 1

        if j >= len(units):
            break

        # Step forward by word budget, not unit count, so overlap is stable
        # regardless of how long individual units are.
        advanced = 0
        while cursor < len(units) and advanced < step:
            advanced += len(units[cursor]["text"].split())
            cursor += 1

    return chunks


def _sample_chunks_evenly(chunks: List[Chunk], limit: int) -> List[Chunk]:
    """
    Keep `limit` chunks spread across the whole timeline.

    Truncating to the first N chunks would hand the LLM only the opening of the
    video, which is the exact failure mode this module exists to prevent.
    """
    if len(chunks) <= limit:
        return chunks
    idxs = np.linspace(0, len(chunks) - 1, limit).round().astype(int)
    return [chunks[i] for i in sorted(set(idxs.tolist()))]


# =====================================================================
# LLM EXTRACTION
# =====================================================================

def _fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


async def _extract_from_chunk(ollama, chunk: Chunk, max_concepts: int, timeout: float) -> List[Concept]:
    """Run one Ollama call for one chunk. Returns [] on any failure."""
    prompt = CONCEPT_PROMPT.format(
        max_concepts=max_concepts,
        start_label=_fmt_time(chunk.start),
        end_label=_fmt_time(chunk.end),
        chunk_text=chunk.text,
    )
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(ollama._generate, prompt, True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        print(f"[Concepts] Chunk {chunk.index} timed out after {timeout}s")
        return []
    except Exception as exc:
        print(f"[Concepts] Chunk {chunk.index} failed: {exc}")
        return []

    parsed = ollama._parse_json(raw) if raw else None
    if not isinstance(parsed, dict):
        return []

    items = parsed.get("concepts")
    if not isinstance(items, list):
        return []

    out: List[Concept] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("concept", "")).strip()
        if not name or len(name) > 80:
            continue
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5
        importance = float(np.clip(importance, 0.0, 1.0))
        evidence = str(item.get("evidence", "")).strip()
        out.append(Concept(
            name=name,
            importance=importance,
            reason=str(item.get("reason", "")).strip(),
            evidence=[evidence] if evidence else [],
            timestamps=[(chunk.start, chunk.end)],
            source="llm",
        ))
    return out


# =====================================================================
# TF-IDF FALLBACK (no LLM required)
# =====================================================================

def extract_concepts_tfidf(chunks: List[Chunk], max_concepts: int = 20) -> List[Concept]:
    """
    Keyphrase concepts without an LLM.

    Scores 1-3 word noun-ish phrases by TF-IDF across chunks, which surfaces
    terms that are frequent in one part of the video but not uniformly present
    everywhere — a decent proxy for "this section is about X". Quality is below
    the LLM path, but it is deterministic, costs no time, and keeps the concept
    signal alive on machines where Ollama is not running.
    """
    if not chunks:
        return []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except Exception:
        return []

    texts = [c.text for c in chunks]
    try:
        vec = TfidfVectorizer(
            stop_words="english",
            ngram_range=(1, 3),
            max_features=4000,
            min_df=1,
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z-]{2,}\b",
        )
        matrix = vec.fit_transform(texts)
    except Exception:
        return []

    terms = np.array(vec.get_feature_names_out())
    if terms.size == 0:
        return []

    dense = matrix.toarray()
    totals = dense.sum(axis=0)
    order = totals.argsort()[::-1]

    concepts: List[Concept] = []
    seen_tokens: List[set] = []

    for pos in order:
        if len(concepts) >= max_concepts:
            break
        phrase = str(terms[pos]).strip()
        tokens = set(phrase.split())
        # Skip a phrase that is mostly contained in one already accepted:
        # "neural network" after "neural networks" adds nothing.
        if any(len(tokens & prev) / max(len(tokens), 1) > 0.6 for prev in seen_tokens):
            continue
        # Which chunks actually carry this term — those are its timestamps.
        hits = np.nonzero(dense[:, pos])[0]
        if hits.size == 0:
            continue
        seen_tokens.append(tokens)
        concepts.append(Concept(
            name=phrase,
            importance=float(totals[pos]),
            reason="Statistically salient phrase across the transcript (TF-IDF).",
            evidence=[],
            timestamps=[(chunks[h].start, chunks[h].end) for h in hits],
            support=int(hits.size),
            source="tfidf",
        ))

    if concepts:
        peak = max(c.importance for c in concepts) or 1.0
        for c in concepts:
            c.importance = float(c.importance / peak)

    return concepts


# =====================================================================
# MERGING AND GLOBAL RANKING
# =====================================================================

def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def merge_concepts(
    concepts: List[Concept],
    embedder=None,
    threshold: float = CONCEPT_MERGE_THRESHOLD,
) -> List[Concept]:
    """
    Collapse duplicate concepts found independently in different chunks.

    Exact-string merging happens first and always. Semantic merging then folds
    together names that differ in wording but not in meaning, using agglomerative
    clustering over SBERT embeddings of the concept names. If SBERT is
    unavailable the string-merged list is returned unchanged — fewer merges, but
    never a wrong one.
    """
    if not concepts:
        return []

    # --- pass 1: exact (normalised) name ---
    by_name: Dict[str, Concept] = {}
    for c in concepts:
        key = _normalise(c.name)
        if not key:
            continue
        if key in by_name:
            _absorb(by_name[key], c)
        else:
            by_name[key] = c
    merged = list(by_name.values())

    if len(merged) < 2:
        return merged

    # --- pass 2: semantic ---
    if embedder is None:
        try:
            from .fusion_engine import get_sentence_transformer
            embedder = get_sentence_transformer()
        except Exception:
            return merged

    try:
        # Embedding "name: reason" rather than the bare name gives the model
        # context; two identical-looking names in different senses stay apart.
        texts = [f"{c.name}. {c.reason}".strip() for c in merged]
        try:
            vectors = np.asarray(embedder.encode(texts, show_progress_bar=False))
        except TypeError:
            vectors = np.asarray(embedder.encode(texts))
    except Exception:
        return merged

    if vectors.ndim != 2 or vectors.shape[0] != len(merged):
        return merged

    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    unit = vectors / np.where(norms < 1e-9, 1e-9, norms)
    for c, v in zip(merged, unit):
        c.embedding = v

    try:
        from sklearn.cluster import AgglomerativeClustering
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=1.0 - threshold,
            metric="cosine",
            linkage="average",
        ).fit_predict(unit)
    except Exception:
        return merged

    grouped: Dict[int, List[Concept]] = {}
    for label, concept in zip(labels, merged):
        grouped.setdefault(int(label), []).append(concept)

    final: List[Concept] = []
    for members in grouped.values():
        # The most-supported, then most-important member names the cluster.
        members.sort(key=lambda c: (c.support, c.importance), reverse=True)
        head = members[0]
        for other in members[1:]:
            _absorb(head, other)
        head.embedding = np.mean([m.embedding for m in members if m.embedding is not None], axis=0)
        final.append(head)

    return final


def _absorb(head: Concept, other: Concept) -> None:
    """Fold `other` into `head`, keeping the strongest signal from each field."""
    head.importance = max(head.importance, other.importance)
    head.support += other.support
    head.timestamps.extend(other.timestamps)
    head.evidence.extend(e for e in other.evidence if e and e not in head.evidence)
    if not head.reason and other.reason:
        head.reason = other.reason
    if _normalise(other.name) != _normalise(head.name) and other.name not in head.aliases:
        head.aliases.append(other.name)


def rank_concepts(concepts: List[Concept], total_duration: float, top_k: int = 25) -> List[Concept]:
    """
    Global importance = local importance x breadth of support x temporal spread.

    Support matters because a concept the LLM independently surfaced in five
    different chunks is more central than one it saw once. Spread matters
    because a concept discussed at 03:00 and again at 47:00 is a through-line of
    the video, not a digression. Both are damped (log / sqrt) so they tilt the
    ranking without letting a merely-repetitive filler phrase outrank a
    genuinely important idea that was explained once, at length.
    """
    if not concepts:
        return []

    for c in concepts:
        support_boost = 1.0 + np.log1p(max(c.support - 1, 0)) * 0.35

        spread = 0.0
        if total_duration > 0 and len(c.timestamps) > 1:
            mids = sorted((a + b) / 2.0 for a, b in c.timestamps)
            spread = (mids[-1] - mids[0]) / total_duration
        spread_boost = 1.0 + np.sqrt(max(spread, 0.0)) * 0.25

        c.importance = float(np.clip(c.importance * support_boost * spread_boost, 0.0, 3.0))
        c.timestamps = sorted(set(c.timestamps))

    peak = max(c.importance for c in concepts) or 1.0
    for c in concepts:
        c.importance = float(c.importance / peak)

    concepts.sort(key=lambda c: c.importance, reverse=True)
    return concepts[:top_k]


# =====================================================================
# PUBLIC ENTRY POINT
# =====================================================================

# Keyed by transcript hash + settings, so re-running a job (or the 5- and
# 10-minute variants of the same video) does not pay for extraction twice.
_CACHE: Dict[str, List[Concept]] = {}


def _cache_key(chunks: List[Chunk], use_llm: bool, max_concepts: int) -> str:
    digest = hashlib.sha1()
    for c in chunks:
        digest.update(c.text[:400].encode("utf-8", "ignore"))
        digest.update(f"{c.start:.1f}".encode())
    digest.update(f"{use_llm}:{max_concepts}".encode())
    return digest.hexdigest()


async def extract_concepts(
    segments: Sequence,
    total_duration: float = 0.0,
    max_concepts_per_chunk: int = 5,
    top_k: int = 25,
    use_llm: bool = True,
    per_chunk_timeout: float = 45.0,
    total_timeout: float = 300.0,
    embedder=None,
) -> List[Concept]:
    """
    Extract, merge and rank the important concepts of one video.

    Never raises. On any failure the return value is the best list obtainable
    from what did work — down to [], which the optimizer handles by falling back
    to semantic relevance and coverage only.

    Args:
        segments:  SemanticSegment list (or timestamped dicts)
        total_duration: source video length in seconds, used for spread scoring
        use_llm:   set False to force the TF-IDF path (fast, deterministic)
        per_chunk_timeout: wall clock for one Ollama call
        total_timeout: wall clock for the whole LLM stage; on expiry whatever
                       finished is kept and the rest is abandoned
    """
    chunks = build_chunks(segments)
    if not chunks:
        return []

    key = _cache_key(chunks, use_llm, top_k)
    if key in _CACHE:
        print(f"[Concepts] Cache hit ({len(_CACHE[key])} concepts)")
        return _CACHE[key]

    raw: List[Concept] = []

    if use_llm:
        ollama = None
        try:
            from .ollama_service import get_ollama_service
            candidate = get_ollama_service()
            if candidate.is_available():
                ollama = candidate
            else:
                print("[Concepts] Ollama unavailable — falling back to TF-IDF concepts")
        except Exception as exc:
            print(f"[Concepts] Ollama service error ({exc}) — falling back to TF-IDF concepts")

        if ollama is not None:
            llm_chunks = _sample_chunks_evenly(chunks, MAX_LLM_CHUNKS)
            if len(llm_chunks) < len(chunks):
                print(f"[Concepts] {len(chunks)} chunks -> sampling {len(llm_chunks)} "
                      f"evenly across the timeline (LLM call cap)")

            tasks = [
                _extract_from_chunk(ollama, ch, max_concepts_per_chunk, per_chunk_timeout)
                for ch in llm_chunks
            ]
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=total_timeout,
                )
            except asyncio.TimeoutError:
                print(f"[Concepts] LLM stage exceeded {total_timeout}s — using partial results")
                results = []

            for res in results:
                if isinstance(res, list):
                    raw.extend(res)

            print(f"[Concepts] LLM produced {len(raw)} raw concepts from {len(llm_chunks)} chunks")

    if not raw:
        raw = extract_concepts_tfidf(chunks, max_concepts=top_k * 2)
        print(f"[Concepts] TF-IDF produced {len(raw)} raw concepts")

    if not raw:
        return []

    if total_duration <= 0:
        total_duration = max((c.end for c in chunks), default=0.0)

    merged = merge_concepts(raw, embedder=embedder)
    ranked = rank_concepts(merged, total_duration=total_duration, top_k=top_k)

    print(f"[Concepts] {len(raw)} raw -> {len(merged)} merged -> {len(ranked)} ranked")
    if ranked:
        preview = ", ".join(f"{c.name} ({c.importance:.2f})" for c in ranked[:6])
        print(f"[Concepts] Top: {preview}")

    _CACHE[key] = ranked
    return ranked


def clear_cache() -> None:
    """Drop the in-process concept cache (used by tests)."""
    _CACHE.clear()
