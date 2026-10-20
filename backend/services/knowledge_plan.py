"""Lightweight concept-to-knowledge-unit planning for the shared selector.

TF-IDF remains the candidate generator.  This module filters obviously noisy
phrases, keeps the existing BGE-canonicalised concepts, and labels evidence in
complete-thought segments with deterministic content roles.  It deliberately
does not call an LLM or create a second selection path.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Dict, List, Optional, Sequence

import numpy as np


UNIT_ROLES = (
    "definition",
    "mechanism_cause",
    "example",
    "comparison_type",
    "detection_evaluation",
    "limitation_pitfall",
    "solution_prevention_application",
)

NARRATIVE_ROLES = ("event", "interaction", "development")

_NARRATIVE_ROLE_PATTERNS = {
    "event": (
        r"\b(?:arrived|left|entered|returned|found|gave|took|started|stopped|happened|occurred|met|joined|lost|won)\b",
    ),
    "interaction": (
        r"\b(?:asked|answered|told|said|replied|called|spoke|talked|thanked|argued|agreed)\b",
    ),
    "development": (
        r"\b(?:then|later|afterwards|eventually|finally|began|became|changed|continued|decided|realized)\b",
    ),
}

_NARRATIVE_ROLE_TIERS = {
    "event": (1, 1.00),
    "interaction": (1, 0.90),
    "development": (1, 0.95),
}

_GENERIC_TERMS = frozenset(
    """
    bit way thing things stuff little looking new particularly times point points
    line object objects humans human people person video videos today okay right
    paul song tempo intensity voice grams wickets coin command underline cs229a mit
    cell cells road light dog dot checkers notebook notebooks gpa anaconda sensor
    discussion section sections using use used user users working work works car cars
    seen minute minutes eat eating ate requirement requirements reason reasons
    example examples feature features featureset system systems application applications
    """.split()
)

_ROLE_PATTERNS = {
    "definition": (
        r"\b(is|are|means|refers to|defined as|called|known as)\b",
        r"\bwhat (is|are)\b",
    ),
    "mechanism_cause": (
        r"\b(because|caused by|happens when|why|mechanism|leads to|results from|works by)\b",
        r"\b(train|training|learns?|fitting|optimi[sz])\w*\b",
        r"\b(allows?|prevents?|resists?|moves?|movement|flow)\b",
    ),
    "example": (
        r"\b(for example|for instance|suppose|imagine|consider|e\.g\.|example)\b",
    ),
    "comparison_type": (
        r"\b(compare|compared|versus|vs\.?|difference|types?|categories|classification|regression)\b",
        r"\b(supervised|unsupervised|reinforcement)\b",
    ),
    "detection_evaluation": (
        r"\b(detect|evaluate|evaluation|metric|accuracy|precision|recall|validation|test set|testing)\b",
        r"\b(train.?test|cross.?validation|error|loss)\b",
    ),
    "limitation_pitfall": (
        r"\b(problem|limitation|pitfall|drawback|risk|fails?|failure|bias|underfit|overfit)\w*\b",
    ),
    "solution_prevention_application": (
        r"\b(prevent|solution|solve|reduce|regulari[sz]|dropout|early stopping|application|used (for|to))\w*\b",
        r"\b(improve|mitigate|avoid|deploy|predict)\w*\b",
    ),
}

# Common educational units that are more specific than a discourse role. They
# remain domain-neutral: the same labels work for statistics, biology, systems,
# or any tutorial that discusses data, training, evaluation and examples.
# (patterns, depth tier, importance).  Tiers are unlocked by the requested
# duration; they are opportunities, never quotas.  Unit evidence must still be
# present in a complete-thought segment.
_KNOWLEDGE_SPECS = {
    "labeled_data": ((r"\b(labeled|labelled|labels?|target variable|input-output examples?)\b",), 1, 1.00),
    "features_and_labels": ((r"\b(features? and labels?|input features?|feature engineering|x and y|inputs? x|outputs? y|mapping from x to y)\b",), 1, 1.00),
    "training_model_fitting": ((r"\b(train|training|fit|fitting|learns? patterns?|model fitting)\w*\b",), 1, 0.95),
    "regression": ((r"\b(linear regression|logistic regression|regression)\b",), 1, 0.95),
    "classification": ((r"\b(classification|classify|classifier|classes)\w*\b",), 1, 0.95),
    "train_test_split": ((r"\b(train(?:ing)? (?:and|/) test|test set|training set|split .{0,30}(?:train|test)|cross.?validation)\b",), 2, 0.90),
    "evaluation": ((r"\b(evaluat|accuracy|precision|recall|f1|error metric|loss function|validation)\w*\b",), 2, 0.90),
    "overfitting": ((r"\b(over.?fit|memor(?:ize|ise).{0,30}train|fails? to generalize|doesn.t generalize)\w*\b",), 2, 0.95),
    "generalization": ((r"\b(generali[sz]|unseen (?:data|examples?|situations?)|new situations?)\w*\b",), 2, 0.90),
    "practical_example": ((r"\b(for example|for instance|suppose|imagine|real.world|application|use case)\b",), 3, 0.80),
    "common_mistake_pitfall": ((r"\b(common mistake|pitfall|data leakage|wrong result|bad patterns?|fails? on new)\w*\b",), 3, 0.80),
    "mitigation_prevention": ((r"\b(prevent|mitigat|regulari[sz]|dropout|early stopping|reduce over.?fit)\w*\b",), 3, 0.85),
    "advanced_detail": ((r"\b(kernel trick|hyperparameter|bias.variance|edge case|neural architecture search)\b",), 4, 0.60),
}

_ROLE_TIERS = {
    "definition": (1, 1.00),
    "mechanism_cause": (1, 0.95),
    "comparison_type": (1, 0.90),
    "example": (1, 0.85),
    "detection_evaluation": (2, 0.85),
    "limitation_pitfall": (3, 0.75),
    "solution_prevention_application": (3, 0.75),
}

_HARD_FILLER_PATTERNS = (
    r"\b(like and subscribe|thanks for watching|welcome to|today'?s lecture)\b",
    r"\b(homework|office hours?|course website|enrollment|subscribe|sponsor|money back guarantee)\b",
)

_QUERY_GLUE = frozenset(
    "what is are explain describe tell show about difference differences between"
    .split()
)


def _stemmed_tokens(text: str) -> List[str]:
    """Small deterministic normaliser for lexical evidence, not a stemmer API."""
    tokens = re.findall(r"\b\w{2,}\b", _normalise(text).replace("-", " "))
    return [
        token[:-1] if len(token) > 4 and token.endswith("s") else token
        for token in tokens
    ]


def _query_facets(query: str, segments: Sequence) -> List[str]:
    """Split explicit intent into transcript-supported facets."""
    clean = re.sub(r"[-_/]+", " ", _normalise(query))
    clauses = re.split(r"\s+(?:and|or|versus|vs)\s+|\s*[,;:]\s*", clean)
    evidence_tokens = set(_stemmed_tokens(" ".join(
        str(getattr(segment, "text", "")) for segment in segments
    )))
    facets = []
    for clause in clauses:
        words = [word for word in _stemmed_tokens(clause) if word not in _QUERY_GLUE]
        if not words or not set(words) <= evidence_tokens:
            continue
        label = " ".join(words)
        if label not in facets:
            facets.append(label)
    return facets


def _facet_evidence(text: str, facet: str) -> float:
    wanted = set(_stemmed_tokens(facet))
    present = set(_stemmed_tokens(text))
    if not wanted or not wanted <= present:
        return 0.0
    return 1.0 if len(wanted) > 1 else 0.85


@dataclass(frozen=True)
class KnowledgeUnit:
    unit_id: str
    concept: str
    role: str
    importance: float
    essential: bool
    tier: int = 1
    candidate_count: int = 0

    def to_dict(self) -> Dict:
        return {
            "unit_id": self.unit_id,
            "concept": self.concept,
            "role": self.role,
            "importance": round(self.importance, 4),
            "essential": self.essential,
            "tier": self.tier,
            "depth": ("essential", "core_depth", "applied_pitfall", "advanced")[self.tier - 1],
            "candidate_count": self.candidate_count,
        }


@dataclass(frozen=True)
class SemanticKnowledgeOccurrence:
    video_id: str
    thought_id: str
    start: float
    end: float
    text: str
    embedding: Optional[np.ndarray] = None
    reference: Optional[str] = None


@dataclass
class KnowledgePlan:
    concepts: List
    units: List[KnowledgeUnit]
    query: str = ""

    def to_dict(self) -> Dict:
        return {
            "query": self.query or None,
            "concepts": [getattr(c, "name", "") for c in self.concepts],
            "units": [unit.to_dict() for unit in self.units],
        }


def _semantic_thought_id(text: str) -> str:
    folded = _normalise(text)
    words = re.findall(r"\b[\w-]{3,}\b", folded)
    seed = " ".join(words[:18]) if words else folded
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _normalise(text: str) -> str:
    return re.sub(r"[^\w\s-]", " ", (text or "").casefold()).strip()


def _is_noise(name: str) -> bool:
    clean = _normalise(name)
    tokens = clean.split()
    if not tokens or len(clean) < 3:
        return True
    if len(tokens) == 1 and tokens[0] in _GENERIC_TERMS:
        return True
    if len(tokens) > 4:
        return True
    return all(token in _GENERIC_TERMS for token in tokens)


def _is_meaningful_semantic_text(text: str) -> bool:
    folded = _normalise(text)
    if not folded:
        return False
    words = re.findall(r"\b[\w-]{3,}\b", folded)
    if len(words) < 4:
        return False
    if _filler_penalty(text) > 0.65:
        return False
    return not all(word in _GENERIC_TERMS for word in words)


def filter_candidate_concepts(
    concepts: Sequence,
    query: str = "",
    query_embedding=None,
) -> List:
    """Remove deterministic noise after TF-IDF generation/canonicalisation."""
    query_tokens = set(_normalise(query).split())
    kept = []
    for concept in concepts or ():
        name = str(getattr(concept, "name", "") or "")
        tokens = set(_normalise(name).split())
        if _is_noise(name) and not (query_tokens and tokens & query_tokens):
            continue
        # These concepts already have source evidence. A broad search title or
        # misspelled query is not an exhaustive vocabulary of its subtopics.
        # Query relevance belongs in the selector's soft score, not a hard
        # filter that deleted all 25 concepts in the computer-course report.
        kept.append(concept)
    return kept


def _roles_for_text(text: str) -> Dict[str, float]:
    folded = (text or "").casefold()
    scores = {}
    for role, patterns in _ROLE_PATTERNS.items():
        hits = sum(bool(re.search(pattern, folded)) for pattern in patterns)
        if hits:
            scores[role] = min(1.0, 0.65 + 0.20 * (hits - 1))
    # A passage without an explicit discourse marker can still be explanatory.
    if not scores:
        scores["mechanism_cause"] = 0.45
    for role, (patterns, _tier, _importance) in _KNOWLEDGE_SPECS.items():
        if any(re.search(pattern, folded) for pattern in patterns):
            scores[role] = 0.90
    return scores


def _narrative_roles_for_text(text: str) -> Dict[str, float]:
    scores = {}
    for role, patterns in _NARRATIVE_ROLE_PATTERNS.items():
        hits = sum(bool(re.search(pattern, text, re.I)) for pattern in patterns)
        if hits:
            scores[role] = min(1.0, 0.75 + 0.15 * (hits - 1))
    return scores


def _filler_penalty(text: str) -> float:
    folded = (text or "").casefold()
    hard_hits = sum(bool(re.search(pattern, folded)) for pattern in _HARD_FILLER_PATTERNS)
    words = max(len(folded.split()), 1)
    discourse = len(re.findall(r"\b(um|uh|you know|sort of|kind of)\b", folded))
    return float(np.clip(0.55 * hard_hits + discourse / words * 1.5, 0.0, 1.0))


def _information_density(text: str, duration: float) -> float:
    words = re.findall(r"\b[\w-]{3,}\b", (text or "").casefold())
    if not words:
        return 0.0
    unique_ratio = len(set(words)) / len(words)
    words_per_second = len(words) / max(float(duration), 1.0)
    pace = np.clip(words_per_second / 2.4, 0.0, 1.0)
    return float(np.clip(0.55 * unique_ratio + 0.45 * pace, 0.0, 1.0))


def _concept_similarity(segment, concept) -> float:
    text = _normalise(getattr(segment, "text", ""))
    name = _normalise(getattr(concept, "name", ""))
    lexical = 1.0 if name and name in text else 0.0
    seg_vec = getattr(segment, "embedding", None)
    con_vec = getattr(concept, "embedding", None)
    semantic = 0.0
    if seg_vec is not None and con_vec is not None:
        a, b = np.asarray(seg_vec, dtype=float), np.asarray(con_vec, dtype=float)
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom > 1e-9:
            semantic = float(np.clip((np.dot(a, b) / denom - 0.50) / 0.50, 0.0, 1.0))
    return max(lexical, semantic)


def build_knowledge_plan(
    segments: Sequence,
    concepts: Sequence,
    query: str = "",
    query_embedding=None,
    budget_seconds: float | None = None,
    content_type: str = "explanatory",
) -> KnowledgePlan:
    """Annotate the existing complete-thought candidates with knowledge units."""
    canonical = filter_candidate_concepts(
        concepts, query=query, query_embedding=query_embedding
    )
    query_name = (query or "").strip()
    if query_name and not any(
        set(_normalise(query_name).split()) <= set(_normalise(getattr(c, "name", "")).split())
        for c in canonical
    ):
        from .concept_extractor import Concept
        root = Concept(
            name=query_name,
            importance=1.0,
            reason="Explicit user learning intent.",
            source="query",
        )
        if query_embedding is not None:
            root.embedding = np.asarray(query_embedding, dtype=float).reshape(-1)
        canonical.insert(0, root)
    units: Dict[str, KnowledgeUnit] = {}
    candidate_counts: Dict[str, int] = {}
    if budget_seconds is None:
        max_tier = 4
    elif budget_seconds <= 5 * 60:
        max_tier = 1
    elif budget_seconds <= 10 * 60:
        max_tier = 2
    elif budget_seconds <= 15 * 60:
        max_tier = 3
    else:
        max_tier = 4
    query_tokens = set(_normalise(query).split())
    query_facets = _query_facets(query, segments) if query_tokens else []
    # With explicit intent, knowledge units belong to the intent root. Related
    # TF-IDF concepts remain useful annotations/candidates, but must not each
    # spawn a second full definition/example/evaluation checklist of their own.
    unit_concepts = (
        [
            c for c in canonical
            if getattr(c, "source", "") == "query"
            or _normalise(getattr(c, "name", "")) == _normalise(query)
        ]
        if query_tokens else list(canonical)
    )

    for segment in segments:
        duration = float(getattr(segment, "duration", 0.0))
        segment.information_density = _information_density(segment.text, duration)
        segment.filler_penalty = _filler_penalty(segment.text)
        segment.knowledge_unit_scores = {}
        segment.knowledge_unit_metadata = {}
        segment.canonical_concepts = []
        segment.semantic_knowledge_unit = ""
        segment.semantic_category = "NOISE/WEAK"
        segment.semantic_occurrence = None

        if _is_meaningful_semantic_text(segment.text):
            thought_id = f"semantic::{_semantic_thought_id(segment.text)}"
            segment.semantic_knowledge_unit = thought_id
            segment.semantic_category = "UNIQUE"
            segment.semantic_occurrence = SemanticKnowledgeOccurrence(
                video_id=str(getattr(segment, "video_id", "")),
                thought_id=thought_id,
                start=float(getattr(segment, "start_time", 0.0)),
                end=float(getattr(segment, "end_time", 0.0)),
                text=str(getattr(segment, "text", "")).strip(),
                embedding=getattr(segment, "embedding", None),
                reference="semantic-thought",
            )
            segment.knowledge_unit_scores[thought_id] = max(
                float(segment.knowledge_unit_scores.get(thought_id, 0.0)),
                0.78,
            )
            segment.knowledge_unit_metadata[thought_id] = {
                "unit_id": thought_id,
                "concept": str(getattr(segment, "canonical_concepts", ["semantic"])[0] if getattr(segment, "canonical_concepts", None) else "semantic"),
                "role": "semantic_thought",
                "importance": 1.0,
                "essential": True,
                "tier": 1,
                "depth": "essential",
                "candidate_count": 1,
                "category": "semantic_knowledge",
                "occurrence": {
                    "video_id": segment.video_id,
                    "thought_id": thought_id,
                    "start": segment.start_time,
                    "end": segment.end_time,
                    "text": segment.text,
                },
            }

        narrative = content_type == "narrative"
        roles = _narrative_roles_for_text(segment.text) if narrative else _roles_for_text(segment.text)

        # Explicit query facets become units only when transcript evidence
        # contains them. Embeddings/TF-IDF still handle semantic expansion.
        for facet in query_facets:
            evidence = _facet_evidence(segment.text, facet)
            if not evidence:
                continue
            unit_id = f"query::{facet.replace(' ', '_')}"
            unit = KnowledgeUnit(
                unit_id=unit_id,
                concept=facet,
                role="query_facet",
                importance=1.0,
                essential=True,
                tier=1,
            )
            units.setdefault(unit_id, unit)
            segment.knowledge_unit_scores[unit_id] = evidence
            segment.knowledge_unit_metadata[unit_id] = unit.to_dict()
            candidate_counts[unit_id] = candidate_counts.get(unit_id, 0) + 1

        # Educational roles become query units when a supported query facet is
        # present, even if a broad query embedding misses the passage.
        facet_strength = max(
            (_facet_evidence(segment.text, facet) for facet in query_facets),
            default=0.0,
        )
        if query_name and facet_strength:
            for role, role_strength in roles.items():
                if narrative:
                    tier, role_importance = _NARRATIVE_ROLE_TIERS[role]
                elif role in _KNOWLEDGE_SPECS:
                    _patterns, tier, role_importance = _KNOWLEDGE_SPECS[role]
                else:
                    tier, role_importance = _ROLE_TIERS[role]
                if tier > max_tier:
                    continue
                unit_id = f"{_normalise(query_name).replace(' ', '_')}::{role}"
                unit = KnowledgeUnit(
                    unit_id=unit_id,
                    concept=query_name,
                    role=role,
                    importance=role_importance,
                    essential=tier == 1,
                    tier=tier,
                )
                units.setdefault(unit_id, unit)
                segment.knowledge_unit_scores[unit_id] = float(np.clip(
                    facet_strength * role_strength, 0.0, 1.0
                ))
                segment.knowledge_unit_metadata[unit_id] = unit.to_dict()
                candidate_counts[unit_id] = candidate_counts.get(unit_id, 0) + 1

        specific_roles = set(roles) if narrative else {
            role for role in roles if role in _KNOWLEDGE_SPECS
        }
        scored_concepts = []
        for concept in canonical:
            evidence = _concept_similarity(segment, concept)
            if evidence >= 0.30:
                scored_concepts.append((evidence, concept))
        # Avoid labelling every passage with every broad phrase.
        scored_concepts.sort(key=lambda item: item[0], reverse=True)
        # Specific lexical evidence (overfitting, generalization, evaluation,
        # etc.) is allowed to attach to the explicit intent root even when a
        # broad query-to-passage cosine falls below the generic concept gate.
        # This fixes lost subtopics without weakening generic role mapping.
        if query_tokens and specific_roles and unit_concepts:
            root = unit_concepts[0]
            if all(root is not item[1] for item in scored_concepts):
                scored_concepts.insert(0, (0.60, root))

        for evidence, concept in scored_concepts[:4]:
            name = str(getattr(concept, "name", ""))
            segment.canonical_concepts.append(name)
            if concept not in unit_concepts:
                continue
            importance = float(getattr(concept, "importance", 0.0))
            concept_tokens = set(_normalise(name).split())
            query_aligned = bool(
                query_tokens
                and (
                    getattr(concept, "source", "") == "query"
                    or concept_tokens == query_tokens
                )
            )
            for role, role_strength in roles.items():
                if narrative:
                    tier, role_importance = _NARRATIVE_ROLE_TIERS[role]
                elif role in _KNOWLEDGE_SPECS:
                    _patterns, tier, role_importance = _KNOWLEDGE_SPECS[role]
                else:
                    tier, role_importance = _ROLE_TIERS[role]
                if tier > max_tier:
                    continue
                unit_id = f"{_normalise(name).replace(' ', '_')}::{role}"
                score = float(np.clip(evidence * role_strength, 0.0, 1.0))
                if score < 0.24:
                    continue
                essential = tier == 1 and (
                    query_aligned or (not query_tokens and importance >= 0.65)
                )
                weighted_importance = importance * role_importance
                unit = KnowledgeUnit(
                    unit_id, name, role, weighted_importance, essential, tier
                )
                units.setdefault(unit_id, unit)
                segment.knowledge_unit_scores[unit_id] = score
                segment.knowledge_unit_metadata[unit_id] = unit.to_dict()
                candidate_counts[unit_id] = candidate_counts.get(unit_id, 0) + 1

    planned = [
        KnowledgeUnit(
            unit.unit_id,
            unit.concept,
            unit.role,
            unit.importance,
            unit.essential,
            unit.tier,
            candidate_counts.get(unit.unit_id, 0),
        )
        for unit in units.values()
    ]
    # Refresh segment metadata with final candidate counts for auditability.
    by_id = {unit.unit_id: unit for unit in planned}
    for segment in segments:
        segment.knowledge_unit_metadata = {
            unit_id: by_id[unit_id].to_dict()
            for unit_id in segment.knowledge_unit_scores
            if unit_id in by_id
        }
    return KnowledgePlan(canonical, planned, query=(query or "").strip())
