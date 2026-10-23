"""Deterministic content semantics and rich-output planning.

This module deliberately does not summarize.  It cleans the selector's frozen
evidence, preserves its metadata, and ranks source-attested text for downstream
DistilBART input and structured output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .text_normalization import sanitize_asr_fragment, topic_keyphrase, sanitize_summary_text


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)
_DIALOGUE_MARKER = re.compile(
    r"(?:^|\s)(?:i|you|we|he|she|they|sir|madam|hey|hello|yes|no|okay|please|thank you)\b",
    re.I,
)
_CONVERSATIONAL_CUE = re.compile(
    r"\b(?:sir|madam|hey|hello|yes|no|okay|please|thank you|excuse me)\b",
    re.I,
)
_EXPLANATORY_MARKER = re.compile(
    r"\b(?:means|defined as|because|therefore|for example|results? in|causes?|"
    r"method|process|step|recommend|conclusion|evidence|study|research)\b",
    re.I,
)
_QUESTION = re.compile(r"\?\s*$")
_SPEAKER_PREFIX = re.compile(r"^\s*[A-Z][\w .'-]{0,24}:\s+")
_QUOTE = re.compile(r"(?:^|\s)[\"'“”]|[\"'“”](?:\s|$)")
_INCOMPLETE_END = re.compile(
    r"\b(?:and|or|but|because|so|that|which|who|when|while|if|to|of|for|with)\s*$",
    re.I,
)
_FIRST_SECOND_PERSON = re.compile(r"\b(?:i|me|my|mine|you|your|yours|we|us|our|ours)\b", re.I)
_HONORIFIC_BREAK = re.compile(r"\b(Mr|Mrs|Ms|Dr|Prof)\.\s+(?=[A-Z])")
_BAD_TOPIC = re.compile(
    r"^(?:i(?:'m| am)?|you(?:'re| are)?|we(?:'re| are)?|let'?s|please|turn|go|come|"
    r"look|okay|yes|no|hey|hello)\b",
    re.I,
)
_EVENT_PREDICATE = re.compile(
    r"\b(?:arriv(?:e|es|ed)|ask(?:s|ed)?|begin(?:s)?|call(?:s|ed)?|"
    r"detain(?:s|ed)?|discover(?:s|ed)?|explain(?:s|ed)?|find(?:s)?|"
    r"introduc(?:e|es|ed)|learn(?:s|ed)?|leave(?:s)?|meet(?:s)?|"
    r"refus(?:e|es|ed)|return(?:s|ed)?|say(?:s|said)|start(?:s|ed)?|"
    r"tell(?:s|ing|told)?|want(?:s|ed)?|work(?:s|ed|ing)?|write(?:s|wrote)|"
    r"appear(?:s|ed)?|encourag(?:e|es|ed))\b",
    re.I,
)
_FIRST_PERSON = re.compile(r"(?:^|[\s\"“])(?:I|I'm|I've|I'll|I'd|my|me)\b")


@dataclass
class ContentTypeResult:
    content_type: str
    confidence: float
    signals: Dict[str, float]


@dataclass
class ContentBlock:
    clean_text: str
    video_id: str
    start_time: float
    end_time: float
    manifest_positions: List[int]
    concepts: List[str] = field(default_factory=list)
    knowledge_units: List[str] = field(default_factory=list)
    importance: float = 0.0


@dataclass
class ContentPlan:
    content_type: str
    confidence: float
    blocks: List[ContentBlock]

    @property
    def bart_input(self) -> str:
        return "\n\n".join(block.clean_text for block in self.blocks if block.clean_text)


def _words(text: str) -> List[str]:
    return _WORD.findall(text or "")


def _item_value(item: Any, name: str, default=None):
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def detect_content_type(
    segments: Sequence,
    titles: Optional[Sequence[str]] = None,
    structural_segments: Optional[Sequence] = None,
) -> ContentTypeResult:
    """Classify organization style without losing pre-consolidation turns."""
    semantic_texts = [str(_item_value(item, "text", "")).strip() for item in segments or ()]
    semantic_texts = [text for text in semantic_texts if text]
    if structural_segments is not None:
        structural = list(structural_segments)
    else:
        # Compatibility fallback for callers that only possess consolidated
        # text: recover punctuation-delimited utterances without pretending
        # they are the preferred raw caption structure.
        structural = [
            {"text": utterance}
            for text in semantic_texts
            for utterance in re.split(r"(?<=[.!?])\s+", text)
            if utterance.strip()
        ]
    structural_pairs = [
        (item, str(_item_value(item, "text", "")).strip()) for item in structural
    ]
    structural_pairs = [(item, text) for item, text in structural_pairs if text]
    structural = [item for item, _text in structural_pairs]
    texts = [text for _item, text in structural_pairs]
    if not texts or not semantic_texts:
        return ContentTypeResult("explanatory", 0.0, {})

    word_counts = [len(_words(text)) for text in texts]
    short = sum(count <= 12 for count in word_counts) / len(texts)
    dialogue = sum(bool(_DIALOGUE_MARKER.search(text)) for text in texts) / len(texts)
    questions = sum(bool(_QUESTION.search(text)) for text in texts) / len(texts)
    speakers = sum(bool(_SPEAKER_PREFIX.search(text)) for text in texts) / len(texts)
    quotes = sum(bool(_QUOTE.search(text)) for text in texts) / len(texts)
    first_second = sum(bool(_FIRST_SECOND_PERSON.search(text)) for text in texts) / len(texts)
    semantic_sentences = [
        sentence
        for text in semantic_texts
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    ]
    explanatory = sum(
        bool(_EXPLANATORY_MARKER.search(text)) for text in semantic_sentences
    ) / max(len(semantic_sentences), 1)
    total_words = max(sum(word_counts), 1)
    conversation_density = min(
        1.0,
        sum(len(_CONVERSATIONAL_CUE.findall(text)) for text in texts) / total_words * 10.0,
    )
    title_text = " ".join(titles or ()).casefold()
    title_dialogue = float(bool(re.search(r"\b(dialogue|conversation|episode|scene|story|interview|drama)\b", title_text)))

    comparable_pairs = rapid_pairs = response_pairs = 0
    for left_item, right_item, left_text, right_text in zip(structural, structural[1:], texts, texts[1:]):
        left_source = str(_item_value(left_item, "video_id", ""))
        right_source = str(_item_value(right_item, "video_id", ""))
        if left_source and right_source and left_source != right_source:
            continue
        left_end = float(_item_value(left_item, "end_time", _item_value(left_item, "start", 0.0)) or 0.0)
        right_start = float(_item_value(right_item, "start_time", _item_value(right_item, "start", 0.0)) or 0.0)
        gap = right_start - left_end
        if gap < -0.25 or gap > 3.0:
            continue
        comparable_pairs += 1
        if gap <= 1.25 and len(_words(left_text)) <= 16 and len(_words(right_text)) <= 16:
            rapid_pairs += 1
        if _QUESTION.search(left_text) and len(_words(right_text)) <= 16:
            response_pairs += 1
    rapid = rapid_pairs / max(comparable_pairs, 1)
    question_response = response_pairs / max(comparable_pairs, 1)
    structural_score = (
        0.28 * short + 0.20 * first_second + 0.14 * conversation_density
        + 0.13 * rapid + 0.13 * questions + 0.07 * question_response
        + 0.05 * speakers
    )
    semantic_dialogue = sum(bool(_DIALOGUE_MARKER.search(text)) for text in semantic_texts) / len(semantic_texts)

    narrative_score = (
        0.76 * structural_score + 0.16 * semantic_dialogue
        + 0.03 * quotes + 0.05 * title_dialogue - 0.32 * explanatory
    )
    content_type = "narrative" if narrative_score >= 0.43 else "explanatory"
    distance = abs(narrative_score - 0.43)
    confidence = min(0.99, 0.50 + distance * 1.6)
    return ContentTypeResult(content_type, round(confidence, 4), {
        "short_utterance_ratio": round(short, 4),
        "dialogue_marker_ratio": round(dialogue, 4),
        "question_ratio": round(questions, 4),
        "speaker_prefix_ratio": round(speakers, 4),
        "first_second_person_ratio": round(first_second, 4),
        "rapid_adjacent_utterance_ratio": round(rapid, 4),
        "question_response_ratio": round(question_response, 4),
        "conversation_cue_density": round(conversation_density, 4),
        "explanatory_marker_ratio": round(explanatory, 4),
        "structural_score": round(structural_score, 4),
        "structural_segment_count": float(len(texts)),
        "semantic_segment_count": float(len(semantic_texts)),
        "narrative_score": round(narrative_score, 4),
    })


def _clean_evidence(text: str) -> str:
    clean = re.sub(
        r"\[(?:noise|inaudible|music|applause|silence|laughter)\]",
        " ",
        str(text or ""),
        flags=re.I,
    )
    clean = re.sub(r"\b(\w+)(?:\s+\1){2,}\b", r"\1", clean, flags=re.I)
    clean = _HONORIFIC_BREAK.sub(r"\1 ", clean)
    clean = re.sub(r"\s+([,.;!?])", r"\1", clean)
    return " ".join(clean.split()).strip()


def _is_strong_continuation(left: ContentBlock, right_text: str, right: Dict[str, Any]) -> bool:
    """Merge only obvious repaired-clause continuations, never generic similarity."""
    if left.video_id != str(right.get("video_id", "")):
        return False
    if float(right.get("start_time", 0.0)) - left.end_time > 0.75:
        return False
    current_evidence = right.get("start_boundary_evidence") or {}
    explicit_incomplete = (
        current_evidence.get("is_complete") is False
        or bool(_INCOMPLETE_END.search(left.clean_text))
        or (left.clean_text and left.clean_text[-1] not in ".!?" and right_text[:1].islower())
    )
    return bool(explicit_incomplete)


def build_content_plan(
    evidence: Sequence[Dict[str, Any]],
    content_type: str,
    confidence: float = 0.0,
) -> ContentPlan:
    """Clean frozen evidence without inventing, paraphrasing, or broad reordering."""
    blocks: List[ContentBlock] = []
    seen = set()
    for position, item in enumerate(evidence or ()):
        text = _clean_evidence(str(item.get("text", "")))
        if len(_words(text)) < 4 and not (
            content_type == "narrative" and text[-1:] in ".!?" and _words(text)
        ):
            continue
        normalized = re.sub(r"\W+", " ", text.casefold()).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if blocks and _is_strong_continuation(blocks[-1], text, item):
            previous = blocks[-1]
            previous.clean_text = f"{previous.clean_text} {text}".strip()
            previous.end_time = float(item.get("end_time", previous.end_time))
            previous.manifest_positions.append(int(item.get("order", position)))
            previous.concepts = list(dict.fromkeys(previous.concepts + list(item.get("canonical_concepts", ()) or ())))
            previous.knowledge_units = list(dict.fromkeys(previous.knowledge_units + list(item.get("knowledge_units", ()) or ())))
            continue

        density = float(item.get("information_density", 0.0) or 0.0)
        filler = float(item.get("filler_penalty", 0.0) or 0.0)
        query = float(item.get("query_relevance", 0.0) or 0.0)
        importance = max(0.0, 0.45 * density + 0.35 * query + 0.20 * (1.0 - min(filler, 1.0)))
        blocks.append(ContentBlock(
            clean_text=text,
            video_id=str(item.get("video_id", "")),
            start_time=float(item.get("start_time", 0.0)),
            end_time=float(item.get("end_time", item.get("start_time", 0.0))),
            manifest_positions=[int(item.get("order", position))],
            concepts=list(dict.fromkeys(item.get("canonical_concepts", ()) or item.get("covered_concepts", ()) or ())),
            knowledge_units=list(dict.fromkeys(item.get("knowledge_units", ()) or ())),
            importance=importance,
        ))
    return ContentPlan(content_type, confidence, blocks)


def _split_sentences(text: str) -> List[str]:
    return [sentence.strip() for sentence in _SENTENCE_SPLIT.split(text.strip())
            if len(_words(sentence)) >= 5]


def refine_narrative_summary(text: str, limit: int = 8) -> str:
    """Keep complete, source-attested event statements from BART output.

    This is deliberately extractive. It removes dialogue snippets from the
    narrative presentation but never paraphrases or invents connective prose.
    """
    sentences = _split_sentences(text)
    candidates = []
    for index, sentence in enumerate(sentences):
        words = _words(sentence)
        if len(words) < 6 or sentence[-1:] not in ".!?":
            continue
        if _INCOMPLETE_END.search(sentence) or re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof)\.\s*$", sentence):
            continue
        event_hits = len(_EVENT_PREDICATE.findall(sentence))
        if not event_hits:
            continue
        first_person = len(_FIRST_PERSON.findall(sentence))
        quote_marks = sum(sentence.count(mark) for mark in ('"', "“", "”"))
        score = event_hits + 0.15 * min(len(words), 30) - 1.25 * first_person - 0.4 * quote_marks
        if score > 0.5:
            candidates.append((index, sentence, score))
    if len(candidates) < 3:
        return text
    if len(candidates) > limit:
        ranked = sorted(candidates, key=lambda item: (-item[2], item[0]))[:limit]
        candidates = sorted(ranked, key=lambda item: item[0])
    return " ".join(sentence for _index, sentence, _score in candidates)


def _narrative_chapters(sentences: Sequence[str]) -> List[Dict[str, Any]]:
    if not sentences:
        return []
    target = min(5, max(2, round(len(sentences) ** 0.5))) if len(sentences) > 2 else 1
    size = max(1, int(np.ceil(len(sentences) / target)))
    chapters = []
    for start in range(0, len(sentences), size):
        group = list(sentences[start:start + size])
        label = topic_keyphrase(group[:1])
        if not _valid_topic(label):
            label = " ".join(_words(group[0])[:6])
        clean_text = sanitize_summary_text(" ".join(group))
        chapters.append({
            "title": label.title()[:80],
            "text": clean_text,
            "timestamp_seconds": None,
            "timestamp_label": None,
            "video_id": "",
        })
    return chapters


def _normalize_vectors(matrix) -> np.ndarray:
    values = np.asarray(matrix, dtype=float)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    return values / np.maximum(norms, 1e-9)


def _fallback_vectors(texts: Sequence[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer
    try:
        return TfidfVectorizer(stop_words="english", max_features=512).fit_transform(texts).toarray()
    except ValueError:
        return np.eye(len(texts), dtype=float)


def _candidate_penalty(text: str) -> float:
    words = _words(text)
    quote_density = sum(text.count(mark) for mark in ('"', "'", "“", "”")) / max(len(words), 1)
    fragment = float(text[-1:] not in ".!?")
    excessive = max(0.0, (len(words) - 45) / 45)
    return min(1.5, quote_density * 2.0 + fragment * 0.35 + excessive * 0.4)


def _select_diverse(
    sentences: Sequence[str], vectors: np.ndarray, base_scores: Sequence[float], count: int,
) -> List[int]:
    vectors = _normalize_vectors(vectors)
    centroid = _normalize_vectors(np.mean(vectors, axis=0, keepdims=True))[0]
    centrality = vectors @ centroid
    selected: List[int] = []
    while len(selected) < min(count, len(sentences)):
        best = None
        best_score = -1e9
        for index, sentence in enumerate(sentences):
            if index in selected:
                continue
            redundancy = max((float(vectors[index] @ vectors[other]) for other in selected), default=0.0)
            region_bonus = 0.10 if not any(abs(index - other) <= max(1, len(sentences) // 4) for other in selected) else 0.0
            score = 0.58 * float(centrality[index]) + 0.27 * float(base_scores[index]) + region_bonus
            score -= 0.42 * max(0.0, redundancy - 0.55) + _candidate_penalty(sentence)
            if score > best_score:
                best, best_score = index, score
        if best is None:
            break
        selected.append(best)
    return selected


def _valid_topic(label: str) -> bool:
    words = [word.casefold() for word in _words(label)]
    if not (2 <= len(words) <= 5) or _BAD_TOPIC.search(label):
        return False
    if len(set(words)) <= max(1, len(words) // 2):
        return False
    return not all(len(word) <= 3 for word in words)


def _chapter_title(blocks: Sequence[ContentBlock]) -> str:
    concepts = [concept.strip() for block in blocks for concept in block.concepts if concept.strip()]
    for concept in concepts:
        if _valid_topic(concept):
            return concept[:80].title()
    label = topic_keyphrase([block.clean_text for block in blocks])
    if _valid_topic(label):
        return label[:80].title()
    words = _words(blocks[0].clean_text)[:7] if blocks else []
    return " ".join(words).strip().capitalize() or "Selected highlights"


def _chapters(plan: ContentPlan) -> List[Dict[str, Any]]:
    blocks = plan.blocks
    if not blocks:
        return []
    target = min(6, max(2, round(len(blocks) ** 0.5))) if len(blocks) > 2 else 1
    size = max(1, int(np.ceil(len(blocks) / target)))
    groups = [blocks[start:start + size] for start in range(0, len(blocks), size)]
    chapters = []
    for group in groups:
        first_block = group[0]
        start_secs = int(getattr(first_block, "start_time", 0))
        mins, secs = divmod(start_secs, 60)
        ts_label = f"{mins:02d}:{secs:02d}"
        clean_preview = sanitize_summary_text(" ".join(block.clean_text for block in group[:2]))
        chapters.append({
            "title": _chapter_title(group),
            "text": clean_preview,
            "timestamp_seconds": start_secs,
            "timestamp_label": ts_label,
            "video_id": getattr(first_block, "video_id", ""),
        })
    return chapters


def enrich_summary(
    summary_text: str,
    plan: Optional[ContentPlan],
    style: str,
    embedder=None,
    timings: Optional[Dict[str, float]] = None,
):
    """Build global extractive TLDR, takeaways/events, chapters, and topics."""
    from ..models.job import RichOutput

    timings = timings if timings is not None else {}
    total_started = perf_counter()
    summary_text = sanitize_summary_text(summary_text)
    if plan and plan.content_type == "narrative":
        summary_text = refine_narrative_summary(summary_text)
    sentences = _split_sentences(summary_text)
    if not sentences:
        return RichOutput(summary=summary_text, style_applied=style), []
    blocks = plan.blocks if plan else []
    texts = sentences + [block.clean_text for block in blocks]
    encode_started = perf_counter()
    try:
        vectors = embedder.encode(texts, show_progress_bar=False) if embedder is not None else _fallback_vectors(texts)
        vectors = _normalize_vectors(vectors)
        if vectors.shape[0] != len(texts):
            raise ValueError("embedding row count does not match enrichment candidates")
    except Exception:
        vectors = _normalize_vectors(_fallback_vectors(texts))
    timings["phase3_bge_encode"] = round(perf_counter() - encode_started, 4)
    sentence_vectors = vectors[:len(sentences)]
    block_vectors = vectors[len(sentences):]

    sentence_support = []
    for vector in sentence_vectors:
        support = float(np.max(block_vectors @ vector)) if len(block_vectors) else 0.5
        sentence_support.append(support)
    stage_started = perf_counter()
    tldr_indices = sorted(_select_diverse(sentences, sentence_vectors, sentence_support, min(2, len(sentences))))
    tldr = sanitize_summary_text(" ".join(sentences[index] for index in tldr_indices))
    timings["tldr_ranking"] = round(perf_counter() - stage_started, 4)

    stage_started = perf_counter()
    takeaway_indices = _select_diverse(sentences, sentence_vectors, sentence_support, min(5, len(sentences)))
    takeaways = [sanitize_summary_text(sentences[index]) for index in takeaway_indices]
    timings["events_or_takeaways"] = round(perf_counter() - stage_started, 4)

    stage_started = perf_counter()
    topics: List[str] = []
    topic_sources = sentences if plan and plan.content_type == "narrative" else blocks
    for source in topic_sources:
        candidates = [] if isinstance(source, str) else list(source.concepts)
        source_text = source if isinstance(source, str) else source.clean_text
        phrase = topic_keyphrase([source_text])
        if phrase:
            candidates.append(phrase)
        for candidate in candidates:
            clean = sanitize_asr_fragment(candidate)
            if _valid_topic(clean) and clean.casefold() not in {item.casefold() for item in topics}:
                topics.append(clean)
                break
        if len(topics) >= 10:
            break
    timings["topic_refinement"] = round(perf_counter() - stage_started, 4)

    stage_started = perf_counter()
    chapters = (
        _narrative_chapters(sentences)
        if plan and plan.content_type == "narrative"
        else (_chapters(plan) if plan else [])
    )
    timings["chapters"] = round(perf_counter() - stage_started, 4)
    timings["total_enrichment"] = round(perf_counter() - total_started, 4)

    return RichOutput(
        summary=summary_text,
        tldr=tldr,
        key_takeaways=takeaways,
        chapters=chapters,
        style_applied=style,
    ), topics
