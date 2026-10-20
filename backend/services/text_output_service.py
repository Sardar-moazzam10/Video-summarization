"""Manifest-only written-summary planning, fallback generation and validation.

This module has no dependency on media files, FFmpeg, transcript acquisition or
selection. It is therefore safe to run in a dedicated text worker process.
"""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Dict, Iterable, List, Sequence

from ..models.output_contracts import (
    EvidenceManifest,
    EvidenceSegment,
    GroundedTakeaway,
    GroundedText,
    KeywordCoverage,
    StructuredTextOutput,
)


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def resolve_text_mode(manifest: EvidenceManifest) -> str:
    return f"{manifest.intent.summary_scope}_{manifest.intent.source_scope}"


def build_evidence_matrix(manifest: EvidenceManifest) -> dict:
    """Keep keyword, topic and source dimensions independent."""
    by_source: Dict[str, List[str]] = defaultdict(list)
    by_keyword: Dict[str, List[str]] = {
        keyword: [] for keyword in manifest.intent.keywords
    }
    by_concept: Dict[str, List[str]] = defaultdict(list)
    segment_by_id = {segment.segment_id: segment for segment in manifest.segments}

    for segment in manifest.segments:
        by_source[segment.video_id].append(segment.segment_id)
        for concept in segment.concepts:
            by_concept[concept].append(segment.segment_id)
        score_by_keyword = {
            key.casefold(): float(value)
            for key, value in segment.keyword_scores.items()
        }
        matched_keywords = {item.casefold() for item in segment.keyword_matches}
        for keyword in manifest.intent.keywords:
            normalized_keyword = keyword.casefold()
            score = score_by_keyword.get(normalized_keyword, 0.0)
            lexical = keyword.casefold() in segment.text.casefold()
            if lexical or score >= 0.65 or normalized_keyword in matched_keywords:
                by_keyword[keyword].append(segment.segment_id)

    return {
        "segments": segment_by_id,
        "by_source": dict(by_source),
        "by_keyword": by_keyword,
        "by_concept": dict(by_concept),
    }


def _sentences(text: str) -> List[str]:
    candidates = [item.strip() for item in _SENTENCE.split((text or "").strip())]
    return [item for item in candidates if len(_WORD.findall(item)) >= 5]


def _first_complete_sentence(segment: EvidenceSegment) -> str:
    candidates = _sentences(segment.text)
    if candidates:
        return candidates[0]
    words = segment.text.strip().split()
    text = " ".join(words[:35]).strip(" ,;:-")
    return f"{text}." if text and text[-1:] not in ".!?" else text


def _rank(segments: Iterable[EvidenceSegment]) -> List[EvidenceSegment]:
    return sorted(
        segments,
        key=lambda item: (
            -max(item.keyword_scores.values(), default=0.0),
            -item.importance,
            item.order,
        ),
    )


def _unique_candidates(segments: Sequence[EvidenceSegment]) -> List[tuple]:
    result = []
    seen = set()
    # Callers already establish policy order. Re-ranking here would destroy
    # keyword round-robin balance and let the globally strongest term dominate.
    for segment in segments:
        text = _first_complete_sentence(segment)
        normalized = " ".join(_WORD.findall(text.casefold()))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append((text, segment))
    return result


def _coverage(manifest: EvidenceManifest, matrix: dict) -> List[KeywordCoverage]:
    output = []
    for keyword in manifest.intent.keywords:
        ids = matrix["by_keyword"].get(keyword, [])
        strong = [
            segment_id for segment_id in ids
            if max(
                (
                    float(value)
                    for key, value in matrix["segments"][segment_id].keyword_scores.items()
                    if key.casefold() == keyword.casefold()
                ),
                default=0.0,
            ) >= 0.65
            or keyword.casefold() in matrix["segments"][segment_id].text.casefold()
        ]
        status = "supported" if strong else ("partial" if ids else "unsupported")
        output.append(KeywordCoverage(
            keyword=keyword,
            status=status,
            evidence_ids=strong or ids,
        ))
    return output


def generate_extractive_fallback(manifest: EvidenceManifest) -> StructuredTextOutput:
    """Produce a bounded, fully grounded result when generation is unavailable."""
    matrix = build_evidence_matrix(manifest)
    mode = resolve_text_mode(manifest)
    ordered: List[EvidenceSegment] = []

    if manifest.intent.summary_scope == "keyword":
        # Round-robin prevents the strongest keyword from consuming the result.
        buckets = [
            _rank([matrix["segments"][item] for item in matrix["by_keyword"].get(keyword, [])])
            for keyword in manifest.intent.keywords
        ]
        for position in range(max((len(bucket) for bucket in buckets), default=0)):
            for bucket in buckets:
                if position < len(bucket) and bucket[position] not in ordered:
                    ordered.append(bucket[position])
    else:
        ordered = _rank(manifest.segments)

    if not ordered:
        ordered = _rank(manifest.segments)
    candidates = _unique_candidates(ordered)
    if not candidates:
        raise ValueError("manifest contains no usable written evidence")

    tldr_text, tldr_segment = candidates[0]
    tldr_words = tldr_text.split()
    if len(tldr_words) > 45:
        tldr_text = " ".join(tldr_words[:45]).rstrip(" ,;:-") + "."

    summary = [
        GroundedText(text=text, evidence_ids=[segment.segment_id])
        for text, segment in candidates[:8]
    ]
    takeaways = []
    for text, segment in candidates[1:8]:
        words = text.split()
        concise = " ".join(words[:25]).rstrip(" ,;:-")
        if concise[-1:] not in ".!?":
            concise += "."
        matched = [
            keyword for keyword in manifest.intent.keywords
            if segment.segment_id in matrix["by_keyword"].get(keyword, [])
        ]
        takeaways.append(GroundedTakeaway(
            text=concise,
            evidence_ids=[segment.segment_id],
            keywords=matched,
        ))
        if len(takeaways) == 7:
            break

    result = StructuredTextOutput(
        mode=mode,
        generation_mode="extractive_fallback",
        summary=summary,
        tldr=GroundedText(text=tldr_text, evidence_ids=[tldr_segment.segment_id]),
        key_takeaways=takeaways,
        keyword_coverage=_coverage(manifest, matrix),
        source_contributions={
            source: ids for source, ids in matrix["by_source"].items() if ids
        },
    )
    result.validation = validate_structured_output(result, manifest)
    return result


def _policy_order(manifest: EvidenceManifest, matrix: dict) -> List[EvidenceSegment]:
    if manifest.intent.summary_scope != "keyword":
        return sorted(manifest.segments, key=lambda item: item.order)
    buckets = [
        _rank([matrix["segments"][item] for item in matrix["by_keyword"].get(keyword, [])])
        for keyword in manifest.intent.keywords
    ]
    ordered: List[EvidenceSegment] = []
    for position in range(max((len(bucket) for bucket in buckets), default=0)):
        for bucket in buckets:
            if position < len(bucket) and bucket[position] not in ordered:
                ordered.append(bucket[position])
    ordered.extend(segment for segment in manifest.segments if segment not in ordered)
    return ordered


def _attribute_evidence(text: str, segments: Sequence[EvidenceSegment]) -> List[str]:
    """Attach only the strongest lexical evidence to generated prose."""
    scored = [
        (_jaccard(text, segment.text), segment.order, segment.segment_id)
        for segment in segments
    ]
    scored.sort(key=lambda item: (-item[0], item[1]))
    positive = [segment_id for score, _, segment_id in scored if score > 0]
    return positive[:3]


def generate_structured_text(manifest: EvidenceManifest, summarizer=None) -> StructuredTextOutput:
    """Generate the narrative once; derive other fields from separate evidence.

    Any model error, grounding failure or output-contract violation falls back
    to the deterministic extractive result rather than publishing uncertain
    prose or failing the sibling video output.
    """
    fallback = generate_extractive_fallback(manifest)
    matrix = build_evidence_matrix(manifest)
    ordered = _policy_order(manifest, matrix)
    evidence_text = "\n\n".join(segment.text for segment in ordered if segment.text.strip())
    if not evidence_text:
        return fallback
    try:
        if summarizer is None:
            from .summarization_service import get_summarization_service
            summarizer = get_summarization_service()
        from .duration_profiles import get_profile
        profile = get_profile(manifest.intent.target_duration_minutes)
        summary_text, decision = summarizer.summarize_with_policy(
            evidence_text,
            profile.target_words,
            profile,
            None,
            manifest.intent.content_type,
        )
        summary_text = (summary_text or "").strip()
        if not summary_text:
            return fallback

        # The model's compress path already performs per-chunk grounding. This
        # final whole-output check also covers clean/rewrite paths.
        from .grounding_check import check_grounding
        grounding = check_grounding(summary_text, evidence_text)
        if not grounding.is_grounded:
            return fallback

        sentences = _sentences(summary_text)
        if not sentences:
            return fallback
        paragraphs = []
        for start in range(0, len(sentences), 3):
            paragraph_text = " ".join(sentences[start:start + 3])
            paragraph_evidence = _attribute_evidence(paragraph_text, ordered)
            if not paragraph_evidence:
                return fallback
            paragraphs.append(GroundedText(
                text=paragraph_text,
                evidence_ids=paragraph_evidence,
            ))

        generated = fallback.model_copy(deep=True)
        generated.generation_mode = "generated"
        generated.summary = paragraphs
        validation = validate_structured_output(generated, manifest)
        validation["summarization_decision"] = decision
        validation["grounding"] = {
            "is_grounded": grounding.is_grounded,
            "unsupported_fraction": getattr(grounding, "unsupported_fraction", 0.0),
            "reasons": list(getattr(grounding, "reasons", []) or []),
        }
        generated.validation = validation
        return generated if validation["valid"] else fallback
    except Exception:
        return fallback


def _token_set(text: str) -> set:
    return set(_WORD.findall((text or "").casefold()))


def _jaccard(left: str, right: str) -> float:
    a, b = _token_set(left), _token_set(right)
    return len(a & b) / max(len(a | b), 1)


def validate_structured_output(
    output: StructuredTextOutput,
    manifest: EvidenceManifest,
) -> dict:
    """Deterministic contract checks; never infer factual support from style."""
    evidence_ids = {segment.segment_id for segment in manifest.segments}
    errors = []
    warnings = []
    tldr_words = len(_WORD.findall(output.tldr.text))
    if len(_sentences(output.tldr.text)) != 1:
        errors.append("tldr_must_be_one_sentence")
    if not 5 <= tldr_words <= 45:
        errors.append("tldr_word_limit")
    if not output.tldr.evidence_ids or not set(output.tldr.evidence_ids) <= evidence_ids:
        errors.append("tldr_unknown_evidence")

    if not output.summary:
        errors.append("summary_must_not_be_empty")
    for index, paragraph in enumerate(output.summary):
        if not paragraph.text.strip():
            errors.append(f"summary_{index}_empty")
        if not paragraph.evidence_ids or not set(paragraph.evidence_ids) <= evidence_ids:
            errors.append(f"summary_{index}_unknown_evidence")

    for index, item in enumerate(output.key_takeaways):
        words = len(_WORD.findall(item.text))
        if not 5 <= words <= 25:
            errors.append(f"takeaway_{index}_word_limit")
        if not item.evidence_ids or not set(item.evidence_ids) <= evidence_ids:
            errors.append(f"takeaway_{index}_unknown_evidence")
        if _jaccard(item.text, output.tldr.text) >= 0.80:
            errors.append(f"takeaway_{index}_duplicates_tldr")
        for earlier, previous in enumerate(output.key_takeaways[:index]):
            if _jaccard(item.text, previous.text) >= 0.80:
                errors.append(f"takeaway_{index}_duplicates_{earlier}")

    requested = set(manifest.intent.keywords)
    reported = {item.keyword for item in output.keyword_coverage}
    matrix = build_evidence_matrix(manifest)
    if requested != reported:
        errors.append("keyword_coverage_contract_mismatch")
    for item in output.keyword_coverage:
        if not set(item.evidence_ids) <= evidence_ids:
            errors.append(f"keyword_{item.keyword}_unknown_evidence")
        if not set(item.evidence_ids) <= set(matrix["by_keyword"].get(item.keyword, [])):
            errors.append(f"keyword_{item.keyword}_unmatched_evidence")
        if item.status == "unsupported" and item.evidence_ids:
            errors.append(f"keyword_{item.keyword}_unsupported_has_evidence")
        if item.status != "unsupported" and not item.evidence_ids:
            errors.append(f"keyword_{item.keyword}_supported_without_evidence")
    for source, source_evidence in output.source_contributions.items():
        if source not in {item.video_id for item in manifest.sources}:
            errors.append(f"source_{source}_unknown")
        if not set(source_evidence) <= evidence_ids:
            errors.append(f"source_{source}_unknown_evidence")
        if not set(source_evidence) <= set(matrix["by_source"].get(source, [])):
            errors.append(f"source_{source}_mismatched_evidence")
    if output.generation_mode == "extractive_fallback":
        warnings.append("extractive_fallback_used")
    return {"valid": not errors, "errors": errors, "warnings": warnings}
