"""
Summarization Policy — decides what a fused narrative actually needs.

The bug this replaces
---------------------
summarization_service.hierarchical_summarize() opened with:

    if word_count <= target_words:
        return text

That is a single test doing two jobs, and it gets one of them wrong. It asks
"is this long enough to need compressing?" and then treats the answer as if it
were "is this good enough to ship?".

Measured on this repo's own completed jobs:

    5-minute profile  (target 750)  -> narrative 757 words  -> BART ran
                                    -> 0 raw fusion transitions in the output
    10-minute profile (target 1500) -> narrative 820 words  -> BYPASSED
                                    -> 19 raw "Additionally,/Furthermore,/
                                       Moreover," artifacts shipped to the user

Same engine, same video. The only difference was which side of the threshold the
narrative landed on. Those transitions come from fusion_engine._synthesize_
narrative(), which glues cluster representatives together with a rotating list
of connectives — fine as an intermediate representation, not something a person
should ever read.

The policy
----------
Compression and coherence are separate questions, so they get separate tests:

    needs compression?  -> word count against the target
    is it coherent?     -> artifact density, fragment rate, self-similarity

    COMPRESS  too long                      -> hierarchical BART (unchanged)
    REWRITE   short enough but incoherent   -> clean artifacts, drop near-
                                               duplicate sentences, then a
                                               length-preserving BART pass
    CLEAN     short and coherent            -> light cleanup only, no model
    PASS      nothing to do

Forcing BART on everything was the other obvious fix and is worse: on an already
clean 300-word narrative a compression model drops real content and costs
seconds for nothing. The policy runs the model only where it earns its keep.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import numpy as np


# Connectives fusion_engine injects between clusters. They are the fingerprint
# of un-summarized fused text, because a real speaker does not start one
# sentence in twenty with "Moreover,".
FUSION_TRANSITIONS = (
    "additionally,",
    "furthermore,",
    "moreover,",
    "in related terms,",
    "building on this,",
    "another key point is that",
    "it's also worth noting that",
    "expanding on this idea,",
    "also,",
    "in a related vein,",
    "expanding further,",
)

# Attribution the fusion engine appends to multi-source clusters.
_SOURCE_ARTIFACT = re.compile(r"\s*\(discussed in \d+ videos?\)", re.IGNORECASE)

# A capitalised connective that is NOT preceded by sentence-ending punctuation.
#
# This is the signature that actually shows up in production, and a
# sentence-initial check misses all of it. fusion_engine._synthesize_narrative
# glues clusters with `f"{transition} {content}"`, and on an auto-caption
# transcript the preceding cluster ends without punctuation — so the connective
# lands in the MIDDLE of a sentence:
#
#   "...If I have to do it now, I will come late Additionally, To reach four
#    and five we need Brain cheat code..."
#
# Taken from a real 10-minute job in this repo, which the first version of this
# detector scored as 0% artifacts and "coherent". No English writer produces
# that construction, so an unpunctuated capitalised connective is a
# machine-glue artifact with essentially no false-positive risk.
_MID_SENTENCE_CONNECTIVE = re.compile(
    r"(?<![.!?\u0964])\s+("
    r"Additionally|Furthermore|Moreover|Also|In related terms|Building on this|"
    r"Expanding on this idea|In a related vein|Expanding further"
    r"),\s+"
)

# Mid-sentence connectives per sentence, above which the text is machine-glued.
# Kept low: even one is unnatural, but a threshold of zero would fire on a
# transcript that merely quotes the word.
MID_SENTENCE_LIMIT = 0.10

# Above this share of sentences opening with a fusion connective, the text is
# machine-glued rather than written. One in eight is already unnatural prose;
# real writing sits well under that.
ARTIFACT_DENSITY_LIMIT = 0.12

# A "sentence" with no verb-like structure and under this many words is a
# fragment — the tail of a caption that got clustered on its own.
FRAGMENT_WORD_LIMIT = 4
FRAGMENT_RATE_LIMIT = 0.20

# Adjacent sentences above this cosine similarity are saying the same thing.
SELF_SIMILARITY_THRESHOLD = 0.80
SELF_SIMILARITY_RATE_LIMIT = 0.15

# How far above target a text may sit before it counts as needing compression.
COMPRESSION_TOLERANCE = 1.15


@dataclass
class CoherenceReport:
    """Why the policy decided what it decided. Logged, and useful in the viva."""
    word_count: int = 0
    sentence_count: int = 0
    artifact_density: float = 0.0
    fragment_rate: float = 0.0
    self_similarity_rate: float = 0.0
    source_artifacts: int = 0
    mid_sentence_connectives: int = 0
    is_coherent: bool = True
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "word_count": self.word_count,
            "sentence_count": self.sentence_count,
            "artifact_density": round(self.artifact_density, 4),
            "fragment_rate": round(self.fragment_rate, 4),
            "self_similarity_rate": round(self.self_similarity_rate, 4),
            "source_artifacts": self.source_artifacts,
            "mid_sentence_connectives": self.mid_sentence_connectives,
            "is_coherent": self.is_coherent,
            "reasons": self.reasons,
        }


@dataclass
class PolicyDecision:
    action: str                     # "compress" | "rewrite" | "clean" | "pass"
    reason: str
    report: CoherenceReport
    target_words: int = 0

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "target_words": self.target_words,
            "coherence": self.report.to_dict(),
        }


def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r'(?<=[.!?])\s+', (text or "").strip()) if s.strip()]


# =====================================================================
# COHERENCE ASSESSMENT
# =====================================================================

def assess_coherence(text: str, embedder=None) -> CoherenceReport:
    """
    Three independent symptoms of raw fused text. Any one of them is enough to
    fail; they detect different failures and a text can have only one.
    """
    report = CoherenceReport()
    sentences = split_sentences(text)
    report.word_count = len((text or "").split())
    report.sentence_count = len(sentences)

    if not sentences:
        report.is_coherent = False
        report.reasons.append("empty text")
        return report

    # --- 1. fusion connective density ---
    artifact_hits = sum(
        1 for s in sentences
        if any(s.lower().startswith(t) for t in FUSION_TRANSITIONS)
    )
    # Both placements count as the same defect, so they feed one density.
    mid_hits = len(_MID_SENTENCE_CONNECTIVE.findall(text or ""))
    report.mid_sentence_connectives = mid_hits
    report.artifact_density = (artifact_hits + mid_hits) / len(sentences)
    report.source_artifacts = len(_SOURCE_ARTIFACT.findall(text or ""))

    # --- 2. fragment rate ---
    fragments = sum(1 for s in sentences if len(s.split()) <= FRAGMENT_WORD_LIMIT)
    report.fragment_rate = fragments / len(sentences)

    # --- 3. adjacent self-similarity ---
    # The fusion engine dedups WITHIN a cluster but not ACROSS clusters, so two
    # clusters about the same idea both contribute their representative and the
    # narrative says the same thing twice in a row.
    if len(sentences) > 2:
        vectors = _embed(sentences, embedder)
        if vectors is not None:
            adjacent = np.sum(vectors[:-1] * vectors[1:], axis=1)
            report.self_similarity_rate = float(
                (adjacent > SELF_SIMILARITY_THRESHOLD).sum() / len(adjacent)
            )

    if report.artifact_density > ARTIFACT_DENSITY_LIMIT:
        report.reasons.append(
            f"{artifact_hits + mid_hits} fusion connectives across {len(sentences)} sentences "
            f"({artifact_hits} sentence-initial, {mid_hits} mid-sentence) — "
            f"{report.artifact_density:.0%} > {ARTIFACT_DENSITY_LIMIT:.0%}"
        )
    elif mid_hits / max(len(sentences), 1) > MID_SENTENCE_LIMIT:
        # Mid-sentence gluing is a stronger signal than the sentence-initial
        # kind, so it gets its own lower threshold: a connective spliced into
        # the middle of a clause is never something a writer did on purpose.
        report.reasons.append(
            f"{mid_hits} connectives spliced mid-sentence across {len(sentences)} sentences"
        )
    if report.source_artifacts:
        report.reasons.append(f"{report.source_artifacts} '(discussed in N videos)' artifacts")
    if report.fragment_rate > FRAGMENT_RATE_LIMIT:
        report.reasons.append(
            f"{report.fragment_rate:.0%} of sentences are fragments "
            f"(> {FRAGMENT_RATE_LIMIT:.0%})"
        )
    if report.self_similarity_rate > SELF_SIMILARITY_RATE_LIMIT:
        report.reasons.append(
            f"{report.self_similarity_rate:.0%} of adjacent sentence pairs are near-duplicates "
            f"(> {SELF_SIMILARITY_RATE_LIMIT:.0%})"
        )

    report.is_coherent = not report.reasons
    return report


def _embed(sentences: Sequence[str], embedder=None) -> Optional[np.ndarray]:
    if embedder is None:
        try:
            from .fusion_engine import get_sentence_transformer
            embedder = get_sentence_transformer()
        except Exception:
            return None
    try:
        try:
            matrix = np.asarray(embedder.encode(list(sentences), show_progress_bar=False))
        except TypeError:
            matrix = np.asarray(embedder.encode(list(sentences)))
    except Exception:
        return None
    if matrix.ndim != 2 or matrix.shape[0] != len(sentences):
        return None
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms < 1e-9, 1e-9, norms)


# =====================================================================
# DECISION
# =====================================================================

def decide(text: str, target_words: int, embedder=None) -> PolicyDecision:
    """Choose what to do with a fused narrative. Never raises."""
    word_count = len((text or "").split())
    report = assess_coherence(text, embedder=embedder)

    if word_count == 0:
        return PolicyDecision("pass", "empty input", report, target_words)

    if word_count > target_words * COMPRESSION_TOLERANCE:
        return PolicyDecision(
            "compress",
            f"{word_count} words is above the {target_words}-word target "
            f"(+{COMPRESSION_TOLERANCE:.0%} tolerance)",
            report,
            target_words,
        )

    if not report.is_coherent:
        return PolicyDecision(
            "rewrite",
            "within the word budget but not coherent: " + "; ".join(report.reasons),
            report,
            target_words,
        )

    return PolicyDecision(
        "clean",
        f"{word_count} words, within budget and coherent — light cleanup only",
        report,
        target_words,
    )


# =====================================================================
# TRANSFORMS
# =====================================================================

def clean_text(text: str) -> str:
    """
    Remove fusion scaffolding without touching the content.

    Safe on any input, so it runs on every path including "compress" — a
    connective fed to BART just wastes input tokens.
    """
    if not text:
        return ""

    text = _SOURCE_ARTIFACT.sub("", text)

    # A connective spliced mid-sentence marks a cluster boundary, which IS a
    # sentence boundary — the preceding cluster simply had no terminal
    # punctuation to carry it. Restoring the full stop repairs the seam instead
    # of leaving two thoughts fused into one ungrammatical run.
    text = _MID_SENTENCE_CONNECTIVE.sub(". ", text)

    sentences = split_sentences(text)
    cleaned: List[str] = []
    for sent in sentences:
        low = sent.lower()
        for transition in FUSION_TRANSITIONS:
            if low.startswith(transition):
                stripped = sent[len(transition):].lstrip()
                if stripped:
                    # Restore the capital the connective was carrying.
                    sent = stripped[0].upper() + stripped[1:]
                break
        # Fusion joins cluster sentences with ". ", which doubles up when the
        # source sentence already ended in punctuation.
        sent = re.sub(r'\s*\.\s*\.', '.', sent)
        sent = re.sub(r'\s{2,}', ' ', sent).strip()
        if sent:
            cleaned.append(sent)

    out = " ".join(cleaned)
    return re.sub(r'\s+([,.;:!?])', r'\1', out).strip()


# A dedup pass that removes more than this share of the text has almost
# certainly mistaken structurally similar sentences for restatements — a
# transcript where every sentence follows the same template will do it. Losing
# most of the summary is a far worse outcome than leaving some repetition in,
# so past this point the original is kept.
MAX_DEDUP_LOSS = 0.50


def deduplicate_sentences(
    text: str,
    embedder=None,
    threshold: float = SELF_SIMILARITY_THRESHOLD,
    max_loss: float = MAX_DEDUP_LOSS,
) -> str:
    """
    Drop sentences that restate something already said.

    Compares each sentence against every kept sentence, not just the previous
    one, because the fusion engine can emit the same idea in clusters 2 and 9.
    Order is preserved so the narrative still reads forwards.

    Bounded by `max_loss`: a pass that would delete most of the text is refused
    outright and the input is returned unchanged. Restatement is a nuisance;
    silently shipping a summary with 90% of its content removed is a failure.
    """
    sentences = split_sentences(text)
    if len(sentences) < 2:
        return text

    vectors = _embed(sentences, embedder)
    if vectors is None:
        return text

    kept_idx = [0]
    for i in range(1, len(sentences)):
        similarity = float(max(vectors[i] @ vectors[j] for j in kept_idx))
        if similarity < threshold:
            kept_idx.append(i)

    result = " ".join(sentences[i] for i in kept_idx)

    original_words = len(text.split())
    if original_words and (1.0 - len(result.split()) / original_words) > max_loss:
        print(f"[Policy] Dedup would remove "
              f"{1.0 - len(result.split()) / original_words:.0%} of the text "
              f"(> {max_loss:.0%}) — keeping the original")
        return text

    return result
