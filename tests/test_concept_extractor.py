"""Tests for concept_extractor — chunking, merging, ranking, and the fallbacks."""

import asyncio

import pytest

from backend.services.concept_extractor import (
    Chunk,
    Concept,
    build_chunks,
    clear_cache,
    extract_concepts,
    extract_concepts_tfidf,
    merge_concepts,
    rank_concepts,
    _sample_chunks_evenly,
)
from backend.services.semantic_segmenter import SemanticSegment


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


def make_segments(n=30, duration=40.0, text_fn=None):
    out, t = [], 0.0
    for i in range(n):
        out.append(SemanticSegment(
            "v1", t, t + duration,
            text_fn(i) if text_fn else f"segment {i} " + "content word " * 20,
        ))
        t += duration
    return out


class TestChunking:
    def test_chunks_carry_their_time_range(self):
        chunks = build_chunks(make_segments(30), chunk_words=200)
        assert chunks
        assert chunks[0].start == 0.0
        assert chunks[-1].end == pytest.approx(30 * 40.0)
        for c in chunks:
            assert c.end > c.start

    def test_chunks_overlap(self):
        chunks = build_chunks(make_segments(40), chunk_words=200, overlap_ratio=0.2)
        assert len(chunks) > 1
        # Consecutive chunks share time, which is what stops a concept spanning a
        # boundary from being seen only in fragments.
        assert chunks[1].start < chunks[0].end

    def test_accepts_plain_dicts(self):
        raw = [{"text": "hello world here", "start_time": 0.0, "end_time": 5.0}]
        assert build_chunks(raw)[0].text == "hello world here"

    def test_accepts_transcript_style_dicts(self):
        raw = [{"text": "hello world", "start": 0.0, "duration": 5.0}]
        chunks = build_chunks(raw)
        assert chunks[0].end == pytest.approx(5.0)

    def test_empty(self):
        assert build_chunks([]) == []
        assert build_chunks(None) == []

    def test_sampling_spans_the_whole_timeline_not_just_the_start(self):
        chunks = [Chunk(f"c{i}", i * 100.0, (i + 1) * 100.0, i) for i in range(40)]
        sampled = _sample_chunks_evenly(chunks, 10)
        assert len(sampled) <= 10
        assert sampled[0].index == 0
        # Truncating to the first N would reintroduce the beginning bias.
        assert sampled[-1].index >= 35

    def test_sampling_is_a_noop_below_the_cap(self):
        chunks = [Chunk(f"c{i}", i * 100.0, (i + 1) * 100.0, i) for i in range(5)]
        assert _sample_chunks_evenly(chunks, 10) == chunks


class TestTfidfFallback:
    def test_extracts_topical_phrases(self):
        chunks = [
            Chunk("overfitting regularisation dropout prevents overfitting in deep networks", 0, 100, 0),
            Chunk("transformers attention heads process token sequences in parallel", 100, 200, 1),
            Chunk("evaluation metrics precision recall measure classifier performance", 200, 300, 2),
        ]
        concepts = extract_concepts_tfidf(chunks, max_concepts=10)
        assert concepts
        names = " ".join(c.name for c in concepts).lower()
        assert any(k in names for k in ("overfitting", "transformers", "attention", "metrics"))
        assert all(c.source == "tfidf" for c in concepts)

    def test_importance_is_normalised(self):
        chunks = [Chunk("alpha beta gamma delta epsilon zeta", i * 10.0, (i + 1) * 10.0, i)
                  for i in range(5)]
        concepts = extract_concepts_tfidf(chunks)
        if concepts:
            assert max(c.importance for c in concepts) == pytest.approx(1.0)
            assert all(0.0 <= c.importance <= 1.0 for c in concepts)

    def test_concepts_carry_timestamps(self):
        chunks = [
            Chunk("overfitting overfitting overfitting", 0.0, 100.0, 0),
            Chunk("unrelated material entirely different", 100.0, 200.0, 1),
        ]
        concepts = extract_concepts_tfidf(chunks)
        overfit = [c for c in concepts if "overfitting" in c.name]
        if overfit:
            assert overfit[0].timestamps
            assert overfit[0].timestamps[0][0] == 0.0

    def test_empty(self):
        assert extract_concepts_tfidf([]) == []


class TestMerging:
    def test_exact_duplicates_merge_and_accumulate_support(self, embedder):
        concepts = [
            Concept("Overfitting", 0.8, "a", timestamps=[(0, 10)]),
            Concept("overfitting", 0.9, "b", timestamps=[(20, 30)]),
            Concept("OVERFITTING", 0.5, "c", timestamps=[(40, 50)]),
        ]
        merged = merge_concepts(concepts, embedder=embedder)
        assert len(merged) == 1
        assert merged[0].importance == 0.9      # strongest signal wins
        assert merged[0].support == 3
        assert len(merged[0].timestamps) == 3

    def test_distinct_concepts_survive(self, embedder):
        concepts = [
            Concept("Gradient Descent", 0.8, "optimisation", timestamps=[(0, 10)]),
            Concept("Photosynthesis", 0.7, "biology", timestamps=[(20, 30)]),
        ]
        assert len(merge_concepts(concepts, embedder=embedder)) == 2

    def test_punctuation_variants_merge_without_an_alias(self, embedder):
        """"Over-fitting" normalises to the same key as "Overfitting" — one name,
        not two, so there is nothing to record as an alias."""
        concepts = [
            Concept("Overfitting", 0.9, "same idea here", timestamps=[(0, 10)]),
            Concept("Over-fitting", 0.8, "same idea here", timestamps=[(10, 20)]),
        ]
        merged = merge_concepts(concepts, embedder=embedder)
        assert len(merged) == 1
        assert merged[0].aliases == []

    def test_differently_named_concepts_that_mean_the_same_record_an_alias(self, embedder):
        """A semantic merge keeps the losing name so the user can still find it."""
        reason = "the model memorises the training set instead of learning to generalise"
        concepts = [
            Concept("Overfitting", 0.9, reason, timestamps=[(0, 10)], support=3),
            Concept("Memorisation", 0.8, reason, timestamps=[(10, 20)]),
        ]
        merged = merge_concepts(concepts, embedder=embedder)
        assert len(merged) == 1, "identical reasons should cluster into one concept"
        assert merged[0].name == "Overfitting", "the better-supported name should win"
        assert "Memorisation" in merged[0].aliases

    def test_survives_a_broken_embedder(self):
        class Broken:
            def encode(self, texts, **kw):
                raise RuntimeError("no model")

        concepts = [Concept("A", 0.5), Concept("B", 0.6), Concept("A", 0.7)]
        merged = merge_concepts(concepts, embedder=Broken())
        assert len(merged) == 2, "string merging must still happen without SBERT"

    def test_empty(self, embedder):
        assert merge_concepts([], embedder=embedder) == []


class TestRanking:
    def test_broad_support_outranks_a_single_mention(self):
        wide = Concept("Wide", 0.6, timestamps=[(0, 10), (100, 110), (200, 210), (300, 310)], support=4)
        narrow = Concept("Narrow", 0.6, timestamps=[(0, 10)], support=1)
        ranked = rank_concepts([narrow, wide], total_duration=400.0)
        assert ranked[0].name == "Wide"

    def test_temporal_spread_is_rewarded(self):
        spread = Concept("Spread", 0.6, timestamps=[(0, 10), (900, 910)], support=2)
        clustered = Concept("Clustered", 0.6, timestamps=[(0, 10), (20, 30)], support=2)
        ranked = rank_concepts([spread, clustered], total_duration=1000.0)
        assert ranked[0].name == "Spread"

    def test_importance_stays_normalised(self):
        concepts = [Concept(f"C{i}", 0.1 * i, timestamps=[(0, 10)], support=i + 1) for i in range(1, 6)]
        ranked = rank_concepts(concepts, total_duration=100.0)
        assert max(c.importance for c in ranked) == pytest.approx(1.0)
        assert all(0.0 <= c.importance <= 1.0 for c in ranked)

    def test_top_k_is_honoured(self):
        concepts = [Concept(f"C{i}", 0.5, timestamps=[(0, 10)]) for i in range(50)]
        assert len(rank_concepts(concepts, 100.0, top_k=10)) == 10

    def test_empty(self):
        assert rank_concepts([], 100.0) == []


class TestExtractConcepts:
    def test_tfidf_path_end_to_end(self, embedder):
        segments = make_segments(
            20, text_fn=lambda i: (
                "overfitting regularisation dropout " if i < 7 else
                "transformers attention token embeddings " if i < 14 else
                "evaluation precision recall metrics "
            ) * 8
        )
        concepts = asyncio.run(extract_concepts(segments, total_duration=800.0, use_llm=False, embedder=embedder))
        assert concepts
        assert all(c.source == "tfidf" for c in concepts)
        assert all(hasattr(c, "timestamps") for c in concepts)

    def test_output_is_json_serialisable(self, embedder):
        segments = make_segments(10)
        concepts = asyncio.run(extract_concepts(segments, total_duration=400.0, use_llm=False, embedder=embedder))
        import json
        json.dumps([c.to_dict() for c in concepts])

    def test_results_are_cached(self, embedder):
        segments = make_segments(10)
        first = asyncio.run(extract_concepts(segments, total_duration=400.0, use_llm=False, embedder=embedder))
        calls = embedder.calls
        second = asyncio.run(extract_concepts(segments, total_duration=400.0, use_llm=False, embedder=embedder))
        assert embedder.calls == calls, "identical input must not be recomputed"
        assert [c.to_dict() for c in first] == [c.to_dict() for c in second]
        assert first is not second, "job mutations must not leak into cached concepts"

    def test_empty_input_returns_empty(self):
        assert asyncio.run(extract_concepts([], use_llm=False)) == []

    def test_falls_back_when_ollama_is_unavailable(self, monkeypatch, embedder):
        class DeadOllama:
            def is_available(self):
                return False

        monkeypatch.setattr(
            "backend.services.ollama_service.get_ollama_service", lambda: DeadOllama()
        )
        segments = make_segments(15, text_fn=lambda i: f"topic{i // 5} content words here " * 10)
        concepts = asyncio.run(extract_concepts(segments, total_duration=600.0, use_llm=True, embedder=embedder))
        assert concepts, "must fall back to TF-IDF rather than returning nothing"
        assert all(c.source == "tfidf" for c in concepts)

    def test_llm_path_with_a_stubbed_daemon(self, monkeypatch, embedder):
        class StubOllama:
            def is_available(self):
                return True

            def _generate(self, prompt, expect_json=False, **kwargs):
                return '{"concepts": [{"concept": "Overfitting", "importance": 0.9, ' \
                       '"reason": "core idea", "evidence": "the model memorises"}]}'

            def _parse_json(self, text):
                import json
                return json.loads(text)

        monkeypatch.setattr(
            "backend.services.ollama_service.get_ollama_service", lambda: StubOllama()
        )
        segments = make_segments(15)
        concepts = asyncio.run(extract_concepts(segments, total_duration=600.0, use_llm=True, embedder=embedder))
        assert concepts
        assert concepts[0].name == "Overfitting"
        assert concepts[0].source == "llm"
        assert concepts[0].evidence

    def test_malformed_llm_output_falls_back_rather_than_crashing(self, monkeypatch, embedder):
        class JunkOllama:
            def is_available(self):
                return True

            def _generate(self, prompt, expect_json=False, **kwargs):
                return "I'm sorry, I cannot do that."

            def _parse_json(self, text):
                return None

        monkeypatch.setattr(
            "backend.services.ollama_service.get_ollama_service", lambda: JunkOllama()
        )
        segments = make_segments(15, text_fn=lambda i: f"topic{i // 5} distinctive content here " * 10)
        concepts = asyncio.run(extract_concepts(segments, total_duration=600.0, use_llm=True, embedder=embedder))
        assert all(c.source == "tfidf" for c in concepts)


class TestLLMResilience:
    """
    Regression tests for two failures found while running the real pipeline
    against a live Ollama daemon.
    """

    def test_a_total_timeout_keeps_the_chunks_that_finished(self, monkeypatch, embedder):
        """
        The first version wrapped gather() in wait_for() and set results = []
        on timeout, throwing away every completed chunk along with the slow one.
        """
        import backend.services.concept_extractor as ce

        calls = {"n": 0}

        class SlowTailOllama:
            def is_available(self):
                return True

            def _generate(self, prompt, expect_json=False, **kwargs):
                calls["n"] += 1
                if calls["n"] > 2:
                    import time
                    time.sleep(30)          # never finishes within the deadline
                return ('{"concepts": [{"concept": "Concept%d", "importance": 0.8, '
                        '"reason": "r", "evidence": "e"}]}' % calls["n"])

            def _parse_json(self, text):
                import json
                try:
                    return json.loads(text)
                except Exception:
                    return None

        monkeypatch.setattr(
            "backend.services.ollama_service.get_ollama_service", lambda: SlowTailOllama()
        )
        monkeypatch.setattr(ce, "CHUNK_WORDS", 60)
        monkeypatch.setattr(ce, "MAX_LLM_CHUNKS", 6)

        segments = make_segments(30, text_fn=lambda i: f"chunk {i} " + "filler word " * 12)
        concepts = asyncio.run(extract_concepts(
            segments, total_duration=1200.0, use_llm=True,
            per_chunk_timeout=20.0, total_timeout=2.0, embedder=embedder,
        ))

        assert concepts, "completed chunks were discarded along with the slow ones"
        assert all(c.source == "llm" for c in concepts), (
            "fell back to TF-IDF despite having usable LLM results"
        )

    def test_requests_are_not_all_fired_at_once(self, monkeypatch, embedder):
        """
        Ollama serialises generation. Launching every chunk simultaneously puts
        most of them in a queue where they burn their per-chunk timeout waiting
        instead of generating, so all of them "time out" against a healthy
        daemon. Concurrency must be bounded.
        """
        import threading
        import backend.services.concept_extractor as ce

        state = {"live": 0, "peak": 0}
        lock = threading.Lock()

        class CountingOllama:
            def is_available(self):
                return True

            def _generate(self, prompt, expect_json=False, **kwargs):
                import time
                with lock:
                    state["live"] += 1
                    state["peak"] = max(state["peak"], state["live"])
                time.sleep(0.05)
                with lock:
                    state["live"] -= 1
                return '{"concepts": [{"concept": "X", "importance": 0.5, "reason": "", "evidence": ""}]}'

            def _parse_json(self, text):
                import json
                return json.loads(text)

        monkeypatch.setattr(
            "backend.services.ollama_service.get_ollama_service", lambda: CountingOllama()
        )
        monkeypatch.setattr(ce, "CHUNK_WORDS", 60)

        segments = make_segments(40, text_fn=lambda i: f"chunk {i} " + "filler word " * 12)
        asyncio.run(extract_concepts(
            segments, total_duration=1600.0, use_llm=True,
            per_chunk_timeout=10.0, total_timeout=60.0, embedder=embedder,
        ))

        assert state["peak"] <= ce.LLM_CONCURRENCY, (
            f"{state['peak']} concurrent Ollama calls, limit is {ce.LLM_CONCURRENCY}"
        )
        assert state["peak"] > 0, "the LLM path never ran"


class TestLocalisedScoring:
    """
    Regression tests for the concept-quality failure found by validating a real
    75-minute Stanford CS229 lecture: summing TF-IDF across chunks returned
    "learning, class, data, learn, algorithms, example, bit, time" — words used
    just as freely while reading out the honour code as while teaching
    regression, and spanning the whole runtime so they localised nothing.
    """

    def _lecture_chunks(self):
        # A course with an administrative first half and a technical second.
        admin = ("welcome to the class the room seats three hundred students "
                 "enrollment is large please email the teaching staff ")
        return [
            Chunk(admin + "office hours are posted on the course website", 0, 300, 0),
            Chunk(admin + "the homework deadline and grading policy are online", 300, 600, 1),
            Chunk("supervised learning regression predicts continuous housing prices "
                  "from features of the training data", 600, 900, 2),
            Chunk("classification separates malignant from benign tumours using "
                  "labelled training examples and features", 900, 1200, 3),
            Chunk("reinforcement learning trains a helicopter to fly by rewarding "
                  "good control actions over time", 1200, 1500, 4),
        ]

    def test_prefers_locally_concentrated_terms_over_ubiquitous_ones(self):
        concepts = extract_concepts_tfidf(self._lecture_chunks(), max_concepts=12)
        names = [c.name for c in concepts]
        assert names, "no concepts extracted"
        # Something technical and localised must surface.
        assert any(k in " ".join(names) for k in
                   ("regression", "classification", "helicopter", "tumour", "malignant",
                    "features", "housing", "reinforcement")), names

    def test_timestamps_do_not_smear_across_the_whole_video(self):
        chunks = self._lecture_chunks()
        total = chunks[-1].end
        concepts = extract_concepts_tfidf(chunks, max_concepts=12)
        for c in concepts:
            merged = []
            for a, b in sorted(c.timestamps):
                if merged and a <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], b)
                else:
                    merged.append([a, b])
            covered = sum(b - a for a, b in merged) / total
            assert covered < 0.85, (
                f"concept {c.name!r} spans {covered:.0%} of the video — "
                f"temporal grounding cannot discriminate with a window that wide"
            )

    def test_a_term_in_every_chunk_does_not_dominate(self):
        chunks = [
            Chunk("learning " * 8 + "regression housing prices continuous", 0, 100, 0),
            Chunk("learning " * 8 + "classification tumour malignant benign", 100, 200, 1),
            Chunk("learning " * 8 + "reinforcement helicopter reward control", 200, 300, 2),
        ]
        concepts = extract_concepts_tfidf(chunks, max_concepts=8)
        assert concepts
        # The property under test is that the BARE ubiquitous term loses, not
        # that the word may never appear: "learning regression housing" is a
        # perfectly good concept precisely because the phrase is localised even
        # though one of its words is not.
        assert concepts[0].name != "learning", "the ubiquitous term still ranks first"
        bare = [c for c in concepts if c.name == "learning"]
        if bare:
            assert bare[0].importance < concepts[0].importance
            assert len(bare[0].timestamps) < len(chunks), (
                "a term in every chunk should not claim every chunk as its window"
            )

    def test_uniform_vocabulary_still_yields_a_ranking(self):
        """Degenerate input: every term in every chunk, so nothing is localised."""
        chunks = [Chunk("alpha beta gamma delta epsilon", i * 10.0, (i + 1) * 10.0, i)
                  for i in range(4)]
        concepts = extract_concepts_tfidf(chunks, max_concepts=5)
        assert concepts, "must still return a ranked list rather than collapsing to empty"
        assert max(c.importance for c in concepts) == pytest.approx(1.0)
