"""Shared fixtures. Nothing here downloads a model or touches the network."""

import os
import sys
import zlib

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeEmbedder:
    """
    Deterministic stand-in for SBERT.

    Embeds text as a normalised bag-of-words vector over a hashed vocabulary, so
    texts sharing words are similar and texts sharing none are not. That is the
    only property the code under test relies on, and it makes every assertion
    reproducible without a 400 MB download.
    """

    def __init__(self, dim: int = 64):
        self.dim = dim
        self.calls = 0

    def encode(self, texts, show_progress_bar=False, batch_size=32):
        self.calls += 1
        out = np.zeros((len(texts), self.dim), dtype=float)
        for i, text in enumerate(texts):
            for word in str(text).lower().split():
                # crc32, not hash(): Python salts string hashing per process
                # (PYTHONHASHSEED), so hash() would give this fixture a different
                # vocabulary on every run and make the assertions below flaky.
                out[i, zlib.crc32(word.encode()) % self.dim] += 1.0
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
            else:
                out[i, 0] = 1.0
        return out


@pytest.fixture
def embedder():
    return FakeEmbedder()


def make_transcript(topics, entries_per_topic=12, entry_seconds=2.5, start=0.0):
    """
    Build a synthetic timestamped transcript.

    `topics` is a list of (vocabulary_word, ...) tuples; each topic produces a
    run of entries built from its own words, so a semantic segmenter should find
    a boundary where one topic ends and the next begins.
    """
    segments = []
    t = start
    for topic_words in topics:
        for i in range(entries_per_topic):
            text = " ".join(topic_words) + f" point {i}"
            segments.append({"text": text, "start": round(t, 2), "duration": entry_seconds})
            t += entry_seconds
    return segments


@pytest.fixture
def transcript_factory():
    return make_transcript
