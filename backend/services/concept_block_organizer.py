"""Post-selection concept blocks; the Phase-2 selector remains untouched."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class ConceptBlockStats:
    concept_block_count: int
    duplicate_concept_rejections: int
    complementary_cross_source_additions: int
    source_switches_per_concept: dict

    def to_dict(self):
        return {
            "concept_block_count": self.concept_block_count,
            "duplicate_concept_rejections": self.duplicate_concept_rejections,
            "complementary_cross_source_additions": self.complementary_cross_source_additions,
            "source_switches_per_concept": self.source_switches_per_concept,
        }


def _normalise(value):
    return re.sub(r"[^\w\s-]", " ", str(value or "").casefold()).strip()


def _concept(segment):
    canonical = list(getattr(segment, "canonical_concepts", ()) or ())
    if canonical:
        return _normalise(canonical[0])
    scores = getattr(segment, "concept_scores", {}) or {}
    return _normalise(max(scores, key=scores.get)) if scores else "general"


def _roles(items):
    return {
        key.split("::", 1)[-1]
        for item in items
        for key in (getattr(item, "knowledge_unit_scores", {}) or {})
    }


def _tokens(items):
    return set(re.findall(r"\b[\w-]{4,}\b", " ".join(i.text for i in items).casefold()))


def _source_blocks(items):
    blocks = defaultdict(list)
    for item in items:
        blocks[item.video_id].append(item)
    for values in blocks.values():
        values.sort(key=lambda item: item.start_time)
    return blocks


def _primary_score(items):
    roles = len(_roles(items))
    density = sum(float(getattr(i, "information_density", 0.0)) for i in items) / len(items)
    completeness = sum(float(getattr(i, "completeness", 0.0)) for i in items) / len(items)
    filler = sum(float(getattr(i, "filler_penalty", 0.0)) for i in items) / len(items)
    query = max((float(getattr(i, "query_relevance", 0.0) or 0.0) for i in items), default=0.0)
    return (roles, round(completeness - filler, 6), round(query, 6), round(density, 6))


def _knowledge_unit_key(item):
    return set((getattr(item, "knowledge_unit_scores", {}) or {}).keys())


def _is_paraphrase(primary, candidate):
    primary_text = re.sub(r"\W+", " ", str(getattr(primary, "text", "")).casefold()).strip()
    candidate_text = re.sub(r"\W+", " ", str(getattr(candidate, "text", "")).casefold()).strip()
    if not primary_text or not candidate_text:
        return False
    primary_tokens = set(primary_text.split())
    candidate_tokens = set(candidate_text.split())
    overlap = len(primary_tokens & candidate_tokens)
    union = len(primary_tokens | candidate_tokens)
    lexical_similarity = overlap / max(union, 1)
    role_overlap = _knowledge_unit_key(primary) & _knowledge_unit_key(candidate)
    same_source = getattr(primary, "video_id", None) == getattr(candidate, "video_id", None)
    return lexical_similarity >= 0.8 or (role_overlap and same_source and lexical_similarity >= 0.65)


def _adds_new_information(primary, candidate):
    if candidate is primary:
        return False
    if _is_paraphrase(primary, candidate):
        return False
    primary_units = _knowledge_unit_key(primary)
    candidate_units = _knowledge_unit_key(candidate)
    if candidate_units - primary_units:
        return True
    primary_tokens = set(re.findall(r"\b\w{4,}\b", str(getattr(primary, "text", "")).casefold()))
    candidate_tokens = set(re.findall(r"\b\w{4,}\b", str(getattr(candidate, "text", "")).casefold()))
    novelty = len(candidate_tokens - primary_tokens) / max(len(candidate_tokens) or 1, 1)
    return novelty >= 0.35


def _concept_order(all_candidates, concepts):
    labels = list(dict.fromkeys(_concept(item) for item in all_candidates))
    fallback = {_normalise(getattr(c, "name", "")): i for i, c in enumerate(concepts)}
    votes = defaultdict(int)
    positions = defaultdict(list)
    by_source = defaultdict(list)
    for item in all_candidates:
        by_source[item.video_id].append(item)
    for source_items in by_source.values():
        source_items.sort(key=lambda item: item.start_time)
        sequence = []
        total = max(float(source_items[-1].end_time), 1.0)
        for item in source_items:
            label = _concept(item)
            positions[label].append(float(item.start_time) / total)
            if not sequence or sequence[-1] != label:
                sequence.append(label)
        for i, left in enumerate(sequence):
            for right in sequence[i + 1:]:
                if left != right:
                    votes[(left, right)] += 1

    remaining, ordered = set(labels), []
    while remaining:
        def key(label):
            incoming = sum(v for (a, b), v in votes.items() if b == label and a in remaining)
            outgoing = sum(v for (a, b), v in votes.items() if a == label and b in remaining)
            mean_pos = sum(positions[label]) / max(len(positions[label]), 1)
            return (incoming - outgoing, mean_pos, fallback.get(label, 10_000), label)
        winner = min(remaining, key=key)
        ordered.append(winner)
        remaining.remove(winner)
    return ordered


def organize_concept_blocks(selected, all_candidates, concepts):
    """Arrange selected candidates into contiguous concept/source blocks.

    Each retained unit gets a concept-block role so downstream summary logic can
    distinguish the primary explanation from complementary evidence without
    treating paraphrased restatements as new information.
    """
    grouped = defaultdict(list)
    for item in selected:
        grouped[_concept(item)].append(item)
    order = _concept_order(all_candidates, concepts)
    order.extend(sorted(set(grouped) - set(order)))

    output = []
    rejected = complementary = 0
    switches = {}
    for concept in [name for name in order if name in grouped]:
        sources = _source_blocks(grouped[concept])
        primary_id = max(sorted(sources), key=lambda source: _primary_score(sources[source]))
        primary_items = sorted(sources[primary_id], key=lambda item: (item.start_time, item.end_time))
        primary_item = primary_items[0]
        primary_item.concept_block = concept
        primary_item.concept_block_role = "PRIMARY"

        primary_roles = _roles(primary_items)
        primary_tokens = _tokens(primary_items)
        accepted_sources = [primary_id]

        for source in sorted(sources):
            if source == primary_id:
                continue
            extra_items = sorted(sources[source], key=lambda segment: (segment.start_time, segment.end_time))
            accepted = []
            for item in extra_items:
                roles = _roles([item])
                tokens = _tokens([item])
                novel_roles = roles - primary_roles
                lexical_novelty = len(tokens - primary_tokens) / max(len(tokens), 1)
                filler = float(getattr(item, "filler_penalty", 0.0))
                if novel_roles or (lexical_novelty >= 0.45 and filler < 0.5):
                    item.concept_block = concept
                    item.concept_block_role = "COMPLEMENTARY"
                    accepted.append(item)
                    complementary += 1
                    primary_roles |= roles
                    primary_tokens |= tokens
                else:
                    rejected += 1
                    item.concept_block = concept
                    item.concept_block_role = "REDUNDANT"
            if accepted:
                accepted_sources.append(source)

        retained = []
        for source in accepted_sources:
            source_items = sorted(sources[source], key=lambda segment: (segment.start_time, segment.end_time))
            for item in source_items:
                if item is primary_item:
                    item.concept_block = concept
                    item.concept_block_role = "PRIMARY"
                    retained.append(item)
                    continue
                if item.video_id == primary_id:
                    if _is_paraphrase(primary_item, item):
                        rejected += 1
                        item.concept_block = concept
                        item.concept_block_role = "REDUNDANT"
                        continue
                    item.concept_block = concept
                    item.concept_block_role = "COMPLEMENTARY"
                    retained.append(item)
                    continue
                if getattr(item, "concept_block_role", None) == "COMPLEMENTARY":
                    retained.append(item)
                    continue
                if getattr(item, "concept_block_role", None) == "REDUNDANT":
                    continue

        output.extend(retained)
        switches[concept] = max(0, len(accepted_sources) - 1)

    stats = ConceptBlockStats(len(grouped), rejected, complementary, switches)
    return output, stats
