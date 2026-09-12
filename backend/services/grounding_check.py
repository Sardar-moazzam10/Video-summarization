"""
Post-generation grounding check for BART output.

Complements the n-gram/sentence-repetition degeneration guard in
summarization_service.py, which was built to catch LOOP degeneration (the
same phrase paraphrased and repeated: "not to worry... not to fear... not
in fear..."). That guard measures lexical repetition *within the output
alone*, so it is blind to a structurally different failure: ungrounded
hallucination, where BART -- forced past the point where the input has
genuine content left -- falls back on lexically DIVERSE text memorised
from its CNN/DailyMail fine-tuning data (site-navigation boilerplate:
"Back to Mail Online home", "Contact us", concatenated fake domains). No
two of those sentences repeat each other, so n-gram and sentence-
uniqueness checks pass it straight through.

Real anchor case (job YIszsqhLGIs, 20-min COMPREHENSIVE profile): a
745-word, clean fusion narrative about failure/risk/trust produced a
summary whose second half drifted into DailyMail-style navigation text.
Per-sentence cosine similarity against the source (BAAI/bge-base-en-v1.5,
the same embedder singleton already used by fusion_engine/vector_store)
split cleanly:

    text                                           best-match similarity
    ----------------------------------------------  ----------------------
    genuine extractive/near-verbatim summary lines   0.87 - 1.00
    a deliberately paraphrased (non-verbatim) line    0.72
    the actual hallucinated boilerplate sentences     0.50 - 0.64

SENTENCE_GROUNDING_THRESHOLD (0.65) sits in the ~0.08 gap between the
worst real paraphrase (0.72) and the best hallucinated line (0.64). On
the real bad output, 63% of sentences fell under it with an unbroken
17-sentence run at the tail -- MAX_UNSUPPORTED_FRACTION and
MIN_CONSECUTIVE_UNSUPPORTED are checked independently since either alone
is already far past a normal summary's signature.

The regex layer exists only for the small set of patterns that need no
semantic judgement at all (a concatenated fake domain is never legitimate
spoken content), not as the primary detector -- per the design brief,
grounding must not rely on a denylist alone.
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional, Sequence

from .summarization_policy import _embed as _embed_sentences

# Calibrated against the real anchor case above -- see module docstring.
SENTENCE_GROUNDING_THRESHOLD = 0.65
MAX_UNSUPPORTED_FRACTION = 0.30
MIN_CONSECUTIVE_UNSUPPORTED = 4

# Below this many sentences, per-sentence similarity is too noisy to judge
# (a single short sentence can legitimately paraphrase its source down to
# ~0.6-0.7 similarity without being hallucinated).
MIN_SENTENCES_FOR_GROUNDING_CHECK = 4

# Three or more dot-separated alphanumeric segments ("tomtom.tom.com",
# "tomahrahn.tomarhin.tomam...") never occurs in real spoken transcripts --
# no semantic judgement needed, this alone is decisive.
_DOMAIN_GARBAGE_RE = re.compile(r'\b[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+){2,}\b')

# The exact literal boilerplate observed in the anchor case. A weak,
# supporting signal only (kept short and literal on purpose) -- NOT relied
# on as the primary detector.
_BOILERPLATE_PHRASES = (
    "mail online",
    "back to the page",
    "back to homepage",
    "back to the front page",
)


def _sentence_split(text: str) -> List[str]:
    from .summarization_service import _split_sentences
    return _split_sentences(text)


@dataclass
class GroundingResult:
    is_grounded: bool
    reasons: List[str] = field(default_factory=list)
    unsupported_fraction: float = 0.0
    longest_unsupported_run: int = 0
    unsupported_sentences: List[str] = field(default_factory=list)


def _pattern_reasons(summary_text: str) -> List[str]:
    reasons = []

    domain_hits = _DOMAIN_GARBAGE_RE.findall(summary_text)
    if domain_hits:
        reasons.append(f"domain-like garbage: {domain_hits[:3]}")

    low = summary_text.lower()
    phrase_hits = [p for p in _BOILERPLATE_PHRASES if p in low]
    if phrase_hits:
        reasons.append(f"navigation boilerplate phrase(s): {phrase_hits}")

    # "back to" repeated 3+ times reads as site-navigation drift; real
    # spoken content essentially never says it that often in one summary.
    back_to_count = low.count("back to")
    if back_to_count >= 3:
        reasons.append(f"'back to' repeated {back_to_count}x")

    return reasons


def check_grounding(
    summary_text: str,
    source_text: str,
    embedder=None,
) -> GroundingResult:
    """
    Is `summary_text` actually supported by `source_text` (the exact text
    that was fed into BART)?

    Cheap, deterministic, no extra LLM call: pattern tripwires plus
    per-sentence cosine similarity against the source using the existing
    SBERT singleton.
    """
    reasons = _pattern_reasons(summary_text)

    summary_sentences = _sentence_split(summary_text)
    source_sentences = _sentence_split(source_text)

    if len(summary_sentences) < MIN_SENTENCES_FOR_GROUNDING_CHECK or not source_sentences:
        return GroundingResult(is_grounded=not reasons, reasons=reasons)

    source_vectors = _embed_sentences(source_sentences, embedder)
    summary_vectors = _embed_sentences(summary_sentences, embedder)

    if source_vectors is None or summary_vectors is None:
        # Embedding unavailable -- fail open on the semantic check (the
        # pattern check above still applies) rather than blocking a job.
        return GroundingResult(is_grounded=not reasons, reasons=reasons)

    best_sims = summary_vectors @ source_vectors.T
    best_sims = best_sims.max(axis=1)

    unsupported_flags = best_sims < SENTENCE_GROUNDING_THRESHOLD
    unsupported_count = int(unsupported_flags.sum())
    unsupported_fraction = unsupported_count / len(summary_sentences)

    longest_run = 0
    current_run = 0
    for flag in unsupported_flags:
        current_run = current_run + 1 if flag else 0
        longest_run = max(longest_run, current_run)

    if unsupported_fraction > MAX_UNSUPPORTED_FRACTION:
        reasons.append(
            f"{unsupported_fraction:.0%} of sentences unsupported by source "
            f"(> {MAX_UNSUPPORTED_FRACTION:.0%})"
        )
    if longest_run >= MIN_CONSECUTIVE_UNSUPPORTED:
        reasons.append(
            f"{longest_run} consecutive unsupported sentences "
            f"(>= {MIN_CONSECUTIVE_UNSUPPORTED})"
        )

    unsupported_sentences = [
        s for s, flag in zip(summary_sentences, unsupported_flags) if flag
    ]

    return GroundingResult(
        is_grounded=not reasons,
        reasons=reasons,
        unsupported_fraction=unsupported_fraction,
        longest_unsupported_run=longest_run,
        unsupported_sentences=unsupported_sentences,
    )
