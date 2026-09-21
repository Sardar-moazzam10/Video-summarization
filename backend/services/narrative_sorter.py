"""Deterministic topic ordering without model loading or pairwise inference."""
from collections import defaultdict


def sort_segments(segments, embedder=None, concept_order=None):
    """Choose among source-local queue heads by topic; retain source chronology.

    Cached concept affinities supply semantic evidence. No raw timestamps are
    compared across sources. The embedder parameter is retained for API compatibility.
    """
    sources = defaultdict(list)
    for seg in segments:
        sources[getattr(seg, "video_id", "")].append(seg)
    for queue in sources.values():
        queue.sort(key=lambda s: s.start_time)
    topics = concept_order or list(dict.fromkeys(
        name for seg in segments for name in getattr(seg, "concept_scores", {})
    ))
    ranks = {name: i for i, name in enumerate(topics)}

    def topic_key(seg):
        scores = getattr(seg, "concept_scores", {})
        topic = max(scores, key=scores.get) if scores else None
        return (ranks.get(topic, len(ranks)), -scores.get(topic, 0.0),
                getattr(seg, "video_id", ""))

    ordered = []
    while sources:
        source = min(sources, key=lambda vid: topic_key(sources[vid][0]))
        ordered.append(sources[source].pop(0))
        # Adjacent clips in a local explanation stay together; changing topic
        # across sources must not insert another speaker inside that explanation.
        while sources[source] and sources[source][0].start_time - ordered[-1].end_time <= 1.2:
            ordered.append(sources[source].pop(0))
        if not sources[source]:
            del sources[source]
    return ordered
