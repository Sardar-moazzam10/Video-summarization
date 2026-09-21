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
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np


# Words per LLM chunk.
#
# Sized for prompt-evaluation cost, not for context limits — llama3.2:3b has 8k
# of context and would happily take three times this. On CPU the prompt is
# evaluated token by token before a single output token appears, so chunk size
# is close to a direct multiplier on latency. 450 words keeps a chunk to roughly
# 600 tokens while still being long enough to contain a whole explanation.
CHUNK_WORDS = 450

# Overlap between consecutive chunks. A concept introduced at the end of one
# chunk and explained at the start of the next would otherwise be seen in
# fragments by both calls and scored as weak in each.
CHUNK_OVERLAP_RATIO = 0.15

# Concept names closer than this in SBERT space are the same concept.
#
# This is a FLOOR, not the operating value — see merge_concepts(). An absolute
# cosine threshold is not portable between embedding models: all-MiniLM-L6-v2
# spreads unrelated short strings around 0.2-0.4, while the configured default
# BAAI/bge-base-en-v1.5 packs them above 0.7. Tuned for the former, 0.72 merged
# every concept of a real 25-minute video into a single cluster named "work".
CONCEPT_MERGE_THRESHOLD = 0.72

# The operating threshold is the higher of the floor above and this quantile of
# the observed pairwise similarities, so "unusually similar FOR THIS MODEL AND
# THIS VIDEO" decides the merge rather than a constant that happens to suit one
# encoder. 0.95 merges roughly the closest 5% of pairs.
CONCEPT_MERGE_QUANTILE = 0.95

# If a merge would still collapse the list below this share of its input, the
# threshold is raised until it does not. Dedup that leaves one concept has not
# deduplicated, it has erased.
MIN_MERGE_SURVIVAL = 0.25

# Below this many concepts the similarity distribution is too small to calibrate
# against, so the absolute floor is used unchanged.
MIN_CONCEPTS_FOR_ADAPTIVE = 8

# Hard ceiling on LLM calls for one video, so a 3-hour source cannot make the
# job run for an hour. Beyond this, chunks are sampled evenly across the
# timeline rather than truncated to the start — truncating would reintroduce
# exactly the beginning-bias this whole change exists to remove.
MAX_LLM_CHUNKS = 14

# Concurrent Ollama requests.
#
# Not a throughput knob — a correctness one. Ollama serialises generation, so
# firing all 14 chunk requests at once puts twelve of them in a queue where they
# burn their per-chunk timeout waiting rather than generating. Every chunk then
# "times out" having produced nothing, and the whole stage falls back to TF-IDF
# despite a healthy daemon. Two in flight keeps the daemon busy while leaving
# each request's timeout measuring the thing it is supposed to measure.
LLM_CONCURRENCY = 2

# Token cap for one concept-extraction answer. Five concepts with names, reasons
# and short quotes fit in roughly 300 tokens; the service default of 1536 lets a
# small model ramble for minutes on CPU and then get killed by a timeout with
# nothing to show. The prompt asks for JSON and Ollama's format:json stops at the
# closing brace, so this cap is a backstop rather than the normal exit.
CONCEPT_NUM_PREDICT = 512


# A chunk counts as "discussing" a term only when the term's TF-IDF there is at
# least this fraction of its strongest chunk. Below that it is a mention, not a
# discussion, and letting it through widens the concept's time window until
# temporal grounding stops discriminating.
TFIDF_STRONG_RATIO = 0.35


def _build_token_pattern() -> str:
    """
    Script-agnostic TF-IDF token pattern.

    The pattern this replaced was ``\\b[a-zA-Z][a-zA-Z-]{2,}\\b`` — ASCII only.
    On any non-Latin transcript it matched NOTHING, so TfidfVectorizer produced
    an empty vocabulary, extract_concepts_tfidf() returned [], and the selector
    then ran with zero concepts — silently disabling the concept term, which
    carries the largest single weight in the scoring function. Measured on a
    real 45,165-character Hindi transcript: 0 tokens matched.

    Two things are needed to fix it:

    1. Unicode letters, not [a-zA-Z]. ``[^\\W\\d_]`` is "word character, minus
       digits, minus underscore" = a letter in any script, so tokens still
       cannot begin with a number.

    2. Combining marks. Python's ``\\w`` follows str.isalnum(), which is False
       for a combining mark, so ``\\w`` alone splits a Devanagari word at every
       vowel sign: बनिए -> ब, न, ए. Indic, Arabic, Hebrew and Thai orthography
       all rely on such marks, so the continuation class has to include Unicode
       category M* explicitly.

    Latin behaviour is unchanged — verified token-for-token against the old
    pattern on English text.
    """
    marks = "".join(
        chr(cp) for cp in range(0x0300, 0x1AB0)
        if unicodedata.category(chr(cp)).startswith("M")
    )
    marks = re.sub(r"[\\\]\^\-]", lambda m: "\\" + m.group(), marks)
    # letter (any script) + 2 or more of {word char, combining mark, hyphen}
    return rf"(?u)\b[^\W\d_][\w{marks}-]{{2,}}"


_TOKEN_PATTERN = _build_token_pattern()


# Filler that survives sklearn's written-English stop list but carries no
# meaning in speech. Contractions appear split ("don", "doesn") because the
# tokeniser drops apostrophes.
_SPOKEN_FILLER = frozenset("""
like just really actually basically literally okay yeah yep nope gonna wanna
gotta kinda sorta maybe right sure well know think thing things stuff lot lots
say says said saying tell tells told talk talks talking come comes came going
goes went get gets got give gives gave make makes made take takes took
look looks looked want wants wanted need needs needed let lets mean means
guy guys people person everybody somebody anybody thank thanks please sorry
don doesn didn isn aren wasn weren won wouldn couldn shouldn haven hasn hadn
ll ve re td um uh ah oh hey yes no nah huh hmm so then now here there
""".split())


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


@dataclass(frozen=True)
class ConceptOccurrence:
    """A specific occurrence of a concept grounded in a source video."""
    video_id: str
    start: float
    end: float

    def __post_init__(self):
        start = max(0.0, float(self.start))
        end = max(start, float(self.end))
        object.__setattr__(self, "video_id", str(self.video_id or ""))
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    def to_tuple(self) -> Tuple[float, float]:
        return (self.start, self.end)


@dataclass
class Concept:
    """One important idea, merged across every chunk that mentioned it."""
    name: str
    importance: float = 0.0
    reason: str = ""
    evidence: List[str] = field(default_factory=list)
    # Time windows where this concept was discussed, as (start, end) seconds.
    timestamps: List[tuple] = field(default_factory=list)
    occurrences: List[ConceptOccurrence] = field(default_factory=list)
    support: int = 1                      # how many chunks independently found it
    aliases: List[str] = field(default_factory=list)
    embedding: Optional[np.ndarray] = None
    source: str = "llm"                   # "llm" or "tfidf"

    def __post_init__(self):
        if self.occurrences and not self.timestamps:
            self.timestamps = [(occ.start, occ.end) for occ in self.occurrences]
        elif self.timestamps and not self.occurrences:
            occs = []
            clean_ts = []
            for item in self.timestamps:
                if isinstance(item, ConceptOccurrence):
                    occs.append(item)
                    clean_ts.append((item.start, item.end))
                elif isinstance(item, (tuple, list)):
                    if len(item) == 3 and isinstance(item[0], str):
                        occs.append(ConceptOccurrence(item[0], float(item[1]), float(item[2])))
                        clean_ts.append((float(item[1]), float(item[2])))
                    elif len(item) >= 2:
                        occs.append(ConceptOccurrence("", float(item[-2]), float(item[-1])))
                        clean_ts.append((float(item[-2]), float(item[-1])))
            self.occurrences = occs
            self.timestamps = clean_ts
        elif self.occurrences and self.timestamps:
            clean_ts = []
            for item in self.timestamps:
                if isinstance(item, (tuple, list)) and len(item) >= 2:
                    clean_ts.append((float(item[-2]), float(item[-1])))
                elif isinstance(item, ConceptOccurrence):
                    clean_ts.append((item.start, item.end))
            self.timestamps = clean_ts

    def to_dict(self) -> Dict:
        return {
            "concept": self.name,
            "importance": round(float(self.importance), 4),
            "reason": self.reason,
            "evidence": self.evidence[:3],
            "timestamps": [[a, b] for a, b in self.timestamps],
            "occurrences": [
                {"video_id": o.video_id, "start": o.start, "end": o.end}
                for o in self.occurrences
            ],
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
    video_id: str = ""


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
            video_id = getattr(seg, "video_id", "")
        else:
            text = seg.get("text", "")
            start = seg.get("start_time", seg.get("start", 0.0))
            end = seg.get("end_time")
            if end is None:
                end = float(start) + float(seg.get("duration", 0.0))
            video_id = seg.get("video_id", "")
        text = (text or "").strip()
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        # Invalid intervals must never reach concept extraction. Swapping an
        # inverted interval would fabricate provenance, so reject it.
        if text and end > start >= 0:
            units.append({
                "text": text,
                "start": start,
                "end": end,
                "video_id": str(video_id or ""),
            })

    if not units:
        return []

    step = max(1, int(chunk_words * (1.0 - overlap_ratio)))
    chunks: List[Chunk] = []
    cursor = 0
    idx = 0

    while cursor < len(units):
        current_vid = units[cursor]["video_id"]
        taken: List[Dict] = []
        words = 0
        j = cursor
        while j < len(units) and words < chunk_words:
            # Enforce hard video boundary: never mix units from different videos into one chunk
            if units[j]["video_id"] != current_vid:
                break
            taken.append(units[j])
            words += len(units[j]["text"].split())
            j += 1
        if not taken:
            cursor += 1
            continue

        chunks.append(Chunk(
            text=" ".join(u["text"] for u in taken),
            start=min(u["start"] for u in taken),
            end=max(u["end"] for u in taken),
            index=idx,
            video_id=current_vid,
        ))
        idx += 1

        if j >= len(units):
            break

        # If we broke because of a different video_id, advance cursor directly to the new video's start
        if units[j]["video_id"] != current_vid:
            cursor = j
            continue

        # Step forward by word budget, not unit count, so overlap is stable
        # regardless of how long individual units are.
        advanced = 0
        old_cursor = cursor
        while cursor < j and advanced < step:
            advanced += len(units[cursor]["text"].split())
            cursor += 1
        if cursor <= old_cursor:
            cursor = old_cursor + 1

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
        # The HTTP timeout is set slightly BELOW the asyncio one on purpose, so
        # httpx aborts the request and the worker thread ends. If the asyncio
        # timeout fired first the coroutine would be cancelled while the thread
        # carried on generating — holding a slot on a daemon that serialises
        # requests, and starving every chunk behind it.
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: ollama._generate(
                    prompt,
                    expect_json=True,
                    timeout=max(5.0, timeout - 2.0),
                    num_predict=CONCEPT_NUM_PREDICT,
                )
            ),
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
        ts_tuples = [(chunk.start, chunk.end)]
        occs = [ConceptOccurrence(video_id=getattr(chunk, "video_id", ""), start=chunk.start, end=chunk.end)]
        out.append(Concept(
            name=name,
            importance=importance,
            reason=str(item.get("reason", "")).strip(),
            evidence=[evidence] if evidence else [],
            timestamps=ts_tuples,
            occurrences=occs,
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
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
        # sklearn's list is built for written English and keeps the vocabulary of
        # speech: on a real 82-minute podcast the top concepts came back as
        # "light, sleep, like, day, melatonin, just, wanna, don" — three of the
        # eight being filler. These are not concepts in any video.
        stop_words = list(ENGLISH_STOP_WORDS | _SPOKEN_FILLER)
        vec = TfidfVectorizer(
            stop_words=stop_words,
            ngram_range=(1, 3),
            max_features=4000,
            min_df=1,
            token_pattern=_TOKEN_PATTERN,   # see _build_token_pattern()
        )
        matrix = vec.fit_transform(texts)
    except Exception:
        return []

    terms = np.array(vec.get_feature_names_out())
    if terms.size == 0:
        return []

    dense = matrix.toarray()

    # Rank by LOCALISED salience, not by total mass across the transcript.
    #
    # Summing TF-IDF over every chunk answers "which words does this video use a
    # lot?", and for a lecture the answer is its own title. Measured on a
    # 75-minute CS229 lecture, the top concepts were: learning, class, data,
    # learn, algorithms, example, bit, time — words that appear just as freely
    # while the lecturer is reading out the honour code as while he is teaching
    # regression. They cannot separate subject matter from administration, and
    # they span the whole runtime so they cannot localise anything either.
    #
    # Peak-times-localisation asks a different question: "which words does this
    # video use HEAVILY IN ONE PLACE?" On the same lecture that returns
    # helicopter, malignant, checkers, features, unsupervised learning,
    # mathematical — concepts that are about something, and whose chunks mark
    # where that something is discussed. The square root damps the localisation
    # term so a word appearing exactly once cannot outrank a genuine recurring
    # topic on rarity alone.
    present = (dense > 0).sum(axis=0) / max(len(chunks), 1)
    salience = dense.max(axis=0) * (1.0 - present) ** 0.5
    if salience.max() <= 0:
        # Every surviving term appears in every chunk, so nothing is localised
        # and the whole ranking would collapse to zero. Uniform vocabulary is a
        # real (if unusual) transcript — a single speaker repeating one topic —
        # and it should still yield a ranked list, just one with no localising
        # power. Fall back to raw peak salience.
        salience = dense.max(axis=0)
    order = salience.argsort()[::-1]

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
        # Timestamps come only from chunks where the term is STRONG, not from
        # every chunk it appears in. A passing mention is not a discussion, and
        # including it would smear the concept's window across the whole video —
        # which is what made temporal grounding useless downstream.
        column = dense[:, pos]
        peak = column.max()
        if peak <= 0:
            continue
        hits = np.nonzero(column >= peak * TFIDF_STRONG_RATIO)[0]
        if hits.size == 0:
            continue
        seen_tokens.append(tokens)
        ts_tuples = [(chunks[h].start, chunks[h].end) for h in hits]
        occs = [
            ConceptOccurrence(video_id=getattr(chunks[h], "video_id", ""), start=chunks[h].start, end=chunks[h].end)
            for h in hits
        ]
        concepts.append(Concept(
            name=phrase,
            importance=float(salience[pos]),
            reason="Locally concentrated phrase — used heavily in part of the transcript (TF-IDF).",
            evidence=[],
            timestamps=ts_tuples,
            occurrences=occs,
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
    """
    Lowercase merge key with punctuation stripped.

    Was ``re.sub(r"[^a-z0-9 ]", "", name.lower())`` — ASCII only, so every
    non-Latin concept name normalised to the empty string and was then dropped
    by merge_concepts()'s ``if not key: continue``. That is the second half of
    the same bug as _build_token_pattern(): after the tokeniser was fixed, a
    Hindi transcript produced 50 raw concepts and still ranked 0, because all
    50 keys were "".

    Keeps letters and digits in any script, plus combining marks (which
    ``isalnum()`` reports False for — see _build_token_pattern). Punctuation,
    symbols and hyphens are dropped exactly as before, and ASCII names
    normalise identically to the old implementation.
    """
    cleaned = "".join(
        ch for ch in name.lower()
        if ch.isalnum() or ch.isspace() or unicodedata.category(ch).startswith("M")
    )
    return re.sub(r"\s+", " ", cleaned).strip()


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

    # Self-calibrate against the observed similarity distribution.
    similarity_matrix = unit @ unit.T
    upper = similarity_matrix[np.triu_indices(len(merged), k=1)]
    # A quantile over two or three concepts describes nothing, and would sit
    # exactly on the one pair that ought to merge — excluding it. Below this
    # count the absolute floor is the better estimator.
    if upper.size and len(merged) >= MIN_CONCEPTS_FOR_ADAPTIVE:
        # Nudged below the quantile so pairs AT it merge rather than falling on
        # the wrong side of a strict comparison.
        adaptive = float(np.quantile(upper, CONCEPT_MERGE_QUANTILE)) - 1e-6
        if adaptive > threshold:
            print(f"[Concepts] Merge threshold raised {threshold:.2f} -> {adaptive:.2f} "
                  f"(p{int(CONCEPT_MERGE_QUANTILE * 100)} of observed similarities)")
            threshold = adaptive

    try:
        from sklearn.cluster import AgglomerativeClustering

        labels = None
        for attempt in range(4):
            candidate = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=max(1e-6, 1.0 - threshold),
                metric="cosine",
                linkage="average",
            ).fit_predict(unit)
            survivors = len(set(candidate.tolist()))
            labels = candidate
            # The collapse guard is only meaningful on a real list. With two or
            # three concepts, merging down to one is a legitimate outcome — they
            # may simply be the same idea named twice.
            if len(merged) < MIN_CONCEPTS_FOR_ADAPTIVE:
                break
            if survivors >= max(2, int(len(merged) * MIN_MERGE_SURVIVAL)):
                break
            # Too aggressive: tighten and retry rather than shipping one cluster.
            threshold = 1.0 - (1.0 - threshold) * 0.5
            print(f"[Concepts] Merge collapsed {len(merged)} concepts to {survivors} — "
                  f"tightening threshold to {threshold:.3f}")
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
    head.occurrences.extend(other.occurrences)
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
        if total_duration > 0 and c.occurrences:
            sources = {}
            for occurrence in c.occurrences:
                sources.setdefault(occurrence.video_id, []).append((occurrence.start + occurrence.end) / 2.0)
            spread = sum(max(mids) - min(mids) for mids in sources.values()) / total_duration
        elif total_duration > 0 and len(c.timestamps) > 1:
            mids = sorted((a + b) / 2.0 for a, b in c.timestamps)
            spread = (mids[-1] - mids[0]) / total_duration
        spread_boost = 1.0 + np.sqrt(max(spread, 0.0)) * 0.25

        c.importance = float(np.clip(c.importance * support_boost * spread_boost, 0.0, 3.0))
        c.timestamps = sorted(set(c.timestamps))
        c.occurrences = sorted(set(c.occurrences), key=lambda o: (o.video_id, o.start, o.end))

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


def _cache_key(chunks: List[Chunk], use_llm: bool, max_concepts: int, **config) -> str:
    from .cache_identity import content_key
    return content_key(["concept-v2", use_llm, max_concepts, config,
                        [(c.video_id, c.start, c.end, c.text) for c in chunks]])


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

    from .cache_identity import model_identity
    from ..core.config import get_settings
    key = _cache_key(chunks, use_llm, top_k, model=model_identity(embedder),
                     total_duration=total_duration, max_per_chunk=max_concepts_per_chunk,
                     per_chunk_timeout=per_chunk_timeout, total_timeout=total_timeout,
                     llm_model=get_settings().OLLAMA_MODEL if use_llm else None,
                     merge_threshold=CONCEPT_MERGE_THRESHOLD,
                     merge_quantile=CONCEPT_MERGE_QUANTILE,
                     source_segments=[(s.video_id, s.start_time, s.end_time, s.text)
                                      if hasattr(s, "start_time") else s for s in segments])
    if key in _CACHE:
        print(f"[Concepts] Cache hit ({len(_CACHE[key])} concepts)")
        import copy
        return copy.deepcopy(_CACHE[key])

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

            semaphore = asyncio.Semaphore(LLM_CONCURRENCY)

            async def _guarded(chunk):
                async with semaphore:
                    return await _extract_from_chunk(
                        ollama, chunk, max_concepts_per_chunk, per_chunk_timeout
                    )

            tasks = [asyncio.ensure_future(_guarded(ch)) for ch in llm_chunks]

            # asyncio.wait, not wait_for(gather(...)): on a total-timeout the
            # latter raises and every finished chunk's work is thrown away with
            # it. Here the completed set is kept and only the stragglers are
            # cancelled, so a slow daemon costs coverage, not everything.
            done, pending = await asyncio.wait(tasks, timeout=total_timeout)
            if pending:
                print(f"[Concepts] LLM stage hit {total_timeout}s with {len(pending)} "
                      f"chunk(s) outstanding — keeping the {len(done)} that finished")
                for task in pending:
                    task.cancel()

            for task in done:
                try:
                    res = task.result()
                except Exception:
                    continue
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

    import copy
    if len(_CACHE) >= 32:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = copy.deepcopy(ranked)
    return ranked


def clear_cache() -> None:
    """Drop the in-process concept cache (used by tests)."""
    _CACHE.clear()
