"""
Tests for summarization_policy — the replacement for the BART bypass bug.

The anchor case is real. Job f39f1089 in this repo's database asked for a
10-minute summary (1500-word target), the fusion engine produced 820 words, the
old `if word_count <= target_words: return text` shortcut fired, and 19 raw
"Additionally,/Furthermore,/Moreover," artifacts reached the user.
"""

import pytest

from backend.services.summarization_policy import (
    assess_coherence,
    clean_text,
    decide,
    deduplicate_sentences,
)


def fused_narrative(paragraphs: int = 8) -> str:
    """Reproduce what fusion_engine._synthesize_narrative actually emits."""
    transitions = ["Additionally,", "Furthermore,", "Moreover,", "In related terms,",
                   "Building on this,", "Another key point is that",
                   "It's also worth noting that", "Expanding on this idea,"]
    # Each cluster contributes DIFFERENT material — that is what a cluster is.
    # An earlier version of this fixture repeated one template sentence with only
    # a number changed, which made the dedup pass legitimately delete almost all
    # of it and tested nothing about connective removal.
    subjects = ["gradient descent", "feature scaling", "cross validation", "regularisation",
                "attention heads", "token embeddings", "batch normalisation", "learning rates",
                "loss surfaces", "weight decay", "dropout layers", "early stopping"]
    verbs = ["reshapes", "constrains", "accelerates", "stabilises", "complicates", "clarifies"]
    objects = ["the optimisation problem", "the resulting representation", "downstream accuracy",
               "the training curve", "generalisation behaviour", "convergence speed"]
    parts = ["The model learns patterns from the training data it is given."]
    for i in range(paragraphs):
        parts.append(
            f"{transitions[i % len(transitions)]} {subjects[i % len(subjects)]} "
            f"{verbs[(i * 5) % len(verbs)]} {objects[(i * 7) % len(objects)]} "
            f"in ways practitioners discover only through experiment number {i}."
        )
    return " ".join(parts)


class TestAssessCoherence:
    def test_flags_fusion_connectives(self, embedder):
        report = assess_coherence(fused_narrative(), embedder=embedder)
        assert not report.is_coherent
        assert report.artifact_density > 0.12
        assert any("fusion connective" in r for r in report.reasons)

    def test_flags_source_attribution_artifacts(self, embedder):
        text = ("The speaker explains the concept in detail here (discussed in 3 videos). "
                "A second unrelated statement follows the first one closely.")
        report = assess_coherence(text, embedder=embedder)
        assert report.source_artifacts == 1
        assert not report.is_coherent

    def test_flags_fragments(self, embedder):
        text = "Yeah. Right. Okay so. Um. The model learns from the data it receives."
        report = assess_coherence(text, embedder=embedder)
        assert report.fragment_rate > 0.20
        assert not report.is_coherent

    def test_flags_adjacent_restatement(self, embedder):
        repeated = "Overfitting means the model memorises the training data completely."
        text = " ".join([repeated] * 6)
        report = assess_coherence(text, embedder=embedder)
        assert report.self_similarity_rate > 0.15
        assert not report.is_coherent

    def test_accepts_genuinely_clean_prose(self, embedder):
        text = (
            "Machine learning systems infer rules from examples rather than being "
            "programmed with them directly. A model trained on labelled photographs "
            "eventually recognises objects it has never encountered before. That "
            "generalisation is the whole point of the exercise. When it fails, the "
            "usual culprit is a training set too narrow to represent the real world."
        )
        report = assess_coherence(text, embedder=embedder)
        assert report.is_coherent, report.reasons

    def test_empty_text(self, embedder):
        report = assess_coherence("", embedder=embedder)
        assert not report.is_coherent


class TestDecide:
    def test_long_text_is_compressed(self, embedder):
        text = "word " * 2000
        decision = decide(text, target_words=750, embedder=embedder)
        assert decision.action == "compress"

    def test_THE_BUG_short_but_incoherent_is_rewritten_not_passed_through(self, embedder):
        """
        The exact case the old code got wrong: 820 words against a 1500-word
        target. Under `if word_count <= target_words: return text` this was
        shipped verbatim, connectives and all.
        """
        text = fused_narrative(paragraphs=60)
        word_count = len(text.split())
        assert word_count < 1500, "fixture must sit UNDER the target to reproduce the bug"

        decision = decide(text, target_words=1500, embedder=embedder)
        assert decision.action == "rewrite", (
            f"raw fused text of {word_count} words passed straight through again"
        )

    def test_short_and_clean_is_left_alone(self, embedder):
        text = (
            "Machine learning systems infer rules from examples rather than being "
            "programmed with them directly. A model trained on labelled photographs "
            "eventually recognises objects it has never encountered before. That "
            "generalisation is the whole point of the exercise."
        )
        decision = decide(text, target_words=1500, embedder=embedder)
        assert decision.action == "clean"

    def test_compression_wins_over_coherence_when_both_apply(self, embedder):
        decision = decide(fused_narrative(200), target_words=100, embedder=embedder)
        assert decision.action == "compress"

    def test_empty(self, embedder):
        assert decide("", 750, embedder=embedder).action == "pass"

    def test_decision_is_serialisable_and_explains_itself(self, embedder):
        decision = decide(fused_narrative(60), 1500, embedder=embedder)
        payload = decision.to_dict()
        assert payload["action"] == "rewrite"
        assert payload["reason"]
        assert payload["coherence"]["reasons"]


class TestCleanText:
    def test_removes_leading_connectives_and_restores_capitalisation(self):
        out = clean_text("Additionally, the model learns from data. Moreover, it generalises well.")
        assert "Additionally" not in out
        assert "Moreover" not in out
        assert out.startswith("The model learns")
        assert "It generalises well." in out

    def test_removes_source_attribution(self):
        out = clean_text("The concept is explained clearly (discussed in 3 videos). Next point.")
        assert "discussed in" not in out

    def test_preserves_content_words(self):
        text = "Furthermore, overfitting happens when the model memorises training data."
        out = clean_text(text).lower()   # the connective's capital is moved onto "Overfitting"
        for word in ("overfitting", "memorises", "training", "data"):
            assert word in out

    def test_idempotent(self):
        text = fused_narrative()
        assert clean_text(clean_text(text)) == clean_text(text)

    def test_empty(self):
        assert clean_text("") == ""
        assert clean_text(None) == ""


class TestDeduplicate:
    def test_removes_restatements_and_keeps_order(self, embedder):
        a = "Overfitting means the model memorises the training data."
        b = "Feature engineering shapes raw inputs into useful signals."
        out = deduplicate_sentences(f"{a} {a} {a} {b}", embedder=embedder)
        assert out.count("Overfitting") == 1
        assert "Feature engineering" in out
        assert out.index("Overfitting") < out.index("Feature")

    def test_keeps_distinct_sentences(self, embedder):
        text = ("Alpha covers the first idea entirely. "
                "Beta explains a completely separate matter. "
                "Gamma introduces yet another distinct subject.")
        assert len(deduplicate_sentences(text, embedder=embedder).split(".")) == len(text.split("."))

    def test_single_sentence_untouched(self, embedder):
        text = "Only one sentence here."
        assert deduplicate_sentences(text, embedder=embedder) == text

    def test_survives_a_broken_embedder(self):
        class Broken:
            def encode(self, texts, **kw):
                raise RuntimeError("no model")

        text = "First sentence here. Second sentence here."
        assert deduplicate_sentences(text, embedder=Broken()) == text


class TestServiceIntegration:
    def test_hierarchical_summarize_no_longer_bypasses(self, embedder, monkeypatch):
        """
        End-to-end through SummarizationService, with BART stubbed out.

        The stub records whether the model was invoked at all — the point of the
        fix is that raw fused text no longer skips every transform.
        """
        from backend.services import summarization_service as svc
        from backend.services.duration_profiles import get_profile

        service = svc.SummarizationService()
        calls = []

        def fake_smooth(text, config):
            calls.append(text)
            return text

        monkeypatch.setattr(service, "_smooth", fake_smooth)

        raw = fused_narrative(paragraphs=60)
        out, decision = service.summarize_with_policy(
            raw, target_words=1500, profile=get_profile(10), embedder=embedder
        )

        assert decision["action"] == "rewrite"
        assert calls, "the rewrite path never ran"
        for connective in ("Additionally,", "Furthermore,", "Moreover,"):
            assert connective not in out, f"{connective} survived into the output"
        assert len(out.split()) > 100, "rewrite destroyed the content"
