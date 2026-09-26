"""
Fusion Engine - Multi-Video Intelligence System

This is the CORE AI component that makes the project FYP-worthy.

Features:
- Semantic topic clustering using Sentence-BERT
- Cross-video deduplication
- Conflict detection between sources
- Unified narrative synthesis
- Duration-aware output generation

Pipeline:
    Transcripts → Sentence Extraction → Embedding → Clustering
    → Deduplication → Conflict Detection → Narrative Synthesis
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
import numpy as np
import re
from collections import defaultdict

# Lazy imports for heavy libraries
_sentence_transformer = None
_clustering_model = None


def get_sentence_transformer():
    """Lazy load sentence transformer model from config (defaults to all-MiniLM-L6-v2)."""
    global _sentence_transformer
    if _sentence_transformer is None:
        from sentence_transformers import SentenceTransformer
        from ..core.config import get_hf_token
        try:
            from ..core.config import get_settings
            model_name = get_settings().EMBEDDING_MODEL
        except Exception:
            model_name = "all-MiniLM-L6-v2"
        # None when unset → anonymous, same as before
        _sentence_transformer = SentenceTransformer(model_name, token=get_hf_token())
        token = get_hf_token()
        try:
            _sentence_transformer = SentenceTransformer(model_name, token=token, local_files_only=True)
        except Exception:
            _sentence_transformer = SentenceTransformer(model_name, token=token)
        print(f"[OK] Loaded Sentence-BERT model: {model_name}")
    return _sentence_transformer


@dataclass
class SourcedSentence:
    """A sentence with its source video tracking."""
    text: str
    video_id: str
    video_title: str = ""
    position: int = 0  # Position in original transcript
    manifest_position: int = 0  # Global canonical order for selected-evidence narratives
    embedding: Optional[np.ndarray] = None


@dataclass
class TopicCluster:
    """A cluster of semantically similar sentences."""
    cluster_id: int
    sentences: List[SourcedSentence]
    centroid: Optional[np.ndarray] = None
    representative: str = ""  # Best sentence to represent this cluster
    source_videos: List[str] = field(default_factory=list)
    topic_label: str = ""
    importance_score: float = 0.0


@dataclass
class ConflictPoint:
    """Detected disagreement between video sources."""
    topic: str
    positions: Dict[str, str]  # video_id -> stance/statement
    confidence: float = 0.0
    resolution_strategy: str = "present_all"


@dataclass
class FusionResult:
    """Result of the fusion process."""
    narrative: str
    topics: List[str]
    conflicts: List[ConflictPoint]
    metadata: Dict[str, Any]


class FusionEngine:
    """
    Multi-Video Fusion Engine

    This engine takes transcripts from multiple videos and creates
    a single, coherent narrative that:
    - Eliminates redundancy
    - Detects and handles conflicts
    - Preserves unique insights
    - Adapts to target duration
    """

    # Words per caption-boundary chunk when the input has no punctuation.
    # This is a fusion unit, not a claimed linguistic sentence.  Kept under
    # max_sentence_words so the hard cap can never drop a chunk, and above
    # min_sentence_words so every chunk has enough context for SBERT.
    TARGET_CHUNK_WORDS = 60

    # A meaningful pause between consecutive auto-caption segments (seconds).
    # YouTube's timing data shows inter-sentence gaps of 0.4–1.5 s; within a
    # sentence the gap is typically < 0.2 s.  0.5 s is a safe boundary signal.
    PAUSE_THRESHOLD_S = 0.5

    def __init__(self):
        self.embedder = None  # Lazy loaded
        self.min_sentence_words = 5
        self.max_sentence_words = 100
        self.similarity_threshold = 0.82  # For deduplication (softer to preserve distinct perspectives)

    def _ensure_embedder(self):
        """Ensure embedder is loaded."""
        if self.embedder is None:
            self.embedder = get_sentence_transformer()

    def fuse_transcripts(
        self,
        transcripts: Dict[str, str],  # video_id -> transcript text
        video_titles: Dict[str, str] = None,  # video_id -> title
        target_words: int = 1500,
        include_sources: bool = True,
        include_transitions: bool = True,
        raw_segments: Optional[Dict[str, list]] = None,  # video_id -> [{text,start,duration}]
        selected_evidence: Optional[List[Dict[str, Any]]] = None,
        expected_order: Optional[List[Dict[str, Any]]] = None,
        detect_conflicts: bool = False,
    ) -> FusionResult:
        """
        Main fusion pipeline.

        Args:
            transcripts: Dict mapping video_id to transcript text
            video_titles: Optional dict mapping video_id to title
            target_words: Target output word count
            include_sources: Whether to attribute sources
            include_transitions: Whether to add transition phrases

        Returns:
            FusionResult with narrative, topics, conflicts, and metadata
        """
        start_time = datetime.now()
        video_titles = video_titles or {}
        raw_segments = raw_segments or {}

        selected_order = self._normalize_selected_evidence(selected_evidence)
        if expected_order is not None:
            expected = self._normalize_selected_evidence(expected_order)
            if selected_order != expected:
                raise ValueError("selected evidence order does not match expected manifest order")

        # Step 1: Extract sentences with source tracking. When a canonical
        # manifest has already been frozen, keep that exact global sequence and
        # do not reconstruct evidence grouped by source.
        if selected_evidence is not None and selected_order:
            print(
                f"[Fusion] Processing {len(selected_order)} selected-evidence items in canonical manifest order..."
            )
            sentences = [
                SourcedSentence(
                    text=str(item["text"]).strip(),
                    video_id=str(item["video_id"]),
                    video_title=video_titles.get(str(item["video_id"]), ""),
                    position=i,
                    manifest_position=i,
                )
                for i, item in enumerate(selected_order)
                if str(item.get("text", "")).strip()
            ]
            source_count = len({str(item["video_id"]) for item in selected_order if item.get("video_id")})
        else:
            print(f"[Fusion] Processing {len(transcripts)} transcripts...")
            sentences = self._extract_sentences(transcripts, video_titles, raw_segments)
            source_count = len(transcripts)
        print(f"[Fusion] Extracted {len(sentences)} sentences")

        if len(sentences) < 3:
            selection_order = [(item["video_id"], item["start_time"], item["end_time"]) for item in selected_order]
            return FusionResult(
                narrative=" ".join([s.text for s in sentences]),
                topics=[],
                conflicts=[],
                metadata={
                    "error": "Too few sentences to fuse",
                    "selected_evidence_order": selection_order,
                }
            )

        # Step 2: Generate embeddings
        self._ensure_embedder()
        texts = [s.text for s in sentences]
        embeddings = self.embedder.encode(texts, show_progress_bar=False)
        for i, sent in enumerate(sentences):
            sent.embedding = embeddings[i]
        print(f"[Fusion] Generated embeddings")

        # Step 3: Cluster by topic
        clusters = self._cluster_sentences(sentences, embeddings)
        print(f"[Fusion] Created {len(clusters)} topic clusters")

        # Step 4: Deduplicate within clusters
        deduplicated = self._deduplicate_clusters(clusters)
        print(f"[Fusion] After dedup: {sum(len(c.sentences) for c in deduplicated)} sentences")

        # Step 5: Detect conflicts (cross-source disagreements).
        # Only meaningful with 2+ sources — the feature exists to surface where
        # videos contradict each other. With a single transcript it loads a
        # NLI is opt-in: the normal merge path uses deterministic topic ordering
        # and must not load or run a cross-encoder.
        if detect_conflicts and len(transcripts) > 1:
            conflicts = self._detect_conflicts(deduplicated)
            print(f"[Fusion] Found {len(conflicts)} potential conflicts")
        else:
            conflicts = []
            print("[Fusion] Conflict detection disabled for this request")

        # Step 6: Synthesize narrative.
        # Selected-evidence runs are order-sensitive: the canonical manifest must
        # remain the narrative order even when clustering/deduplication changes
        # the semantic grouping.
        if selected_evidence is not None and selected_order:
            ordered_survivors = sorted(
                (s for cluster in deduplicated for s in cluster.sentences),
                key=lambda s: s.manifest_position,
            )
            self._validate_selected_evidence_narrative(ordered_survivors)
            narrative = self._synthesize_selected_evidence(
                ordered_survivors,
                target_words,
                include_sources,
                include_transitions,
            )
        else:
            narrative = self._synthesize_narrative(
                deduplicated,
                conflicts,
                target_words,
                include_sources,
                include_transitions
            )

        # Calculate metadata
        total_source_words = sum(len(t.split()) for t in transcripts.values())
        if selected_evidence is not None and selected_order:
            total_source_words = sum(len(str(item.get("text", "")).split()) for item in selected_order)
        output_words = len(narrative.split())
        processing_time = (datetime.now() - start_time).total_seconds()

        topics = [c.topic_label for c in deduplicated if c.topic_label][:10]

        metadata = {
            "total_source_words": total_source_words,
            "output_words": output_words,
            "compression_ratio": output_words / max(total_source_words, 1),
            "clusters_created": len(clusters),
            "dedup_ratio": sum(len(c.sentences) for c in deduplicated) / max(len(sentences), 1),
            "processing_time_seconds": processing_time,
            "videos_processed": source_count,
            "selected_evidence_order": [(item["video_id"], item["start_time"], item["end_time"]) for item in selected_order],
        }

        return FusionResult(
            narrative=narrative,
            topics=topics,
            conflicts=conflicts,
            metadata=metadata
        )

    def _normalize_selected_evidence(
        self,
        selected_evidence: Optional[List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """Normalize selected evidence into a manifest-order list."""
        if not selected_evidence:
            return []

        normalized = []
        for item in selected_evidence:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("video_id") or item.get("video") or item.get("source_id") or "")
            text = item.get("text") or item.get("sentence") or ""
            start = item.get("start_time", item.get("start", 0.0))
            end = item.get("end_time", item.get("end", start))
            if not video_id or not str(text).strip():
                continue
            normalized.append({
                "video_id": video_id,
                "start_time": float(start),
                "end_time": float(end),
                "text": str(text).strip(),
            })
        return normalized

    def _extract_sentences(
        self,
        transcripts: Dict[str, str],
        video_titles: Dict[str, str],
        raw_segments: Optional[Dict[str, list]] = None,
    ) -> List[SourcedSentence]:
        """
        Extract sentence-like chunks from transcripts for SBERT clustering.

        Three-tier strategy, applied per video:

          Tier 1 — Segment-boundary chunking (best).
            When timestamped segments are available, accumulate consecutive
            caption entries into chunks using three flush triggers (in priority
            order):
              (a) Natural punctuation end (.!?) on the current segment.
              (b) Accumulated words >= TARGET_CHUNK_WORDS AND the gap to the
                  next segment >= PAUSE_THRESHOLD_S (a meaningful speaker pause).
              (c) Hard cap: accumulated words >= max_sentence_words.
            This handles auto-generated YouTube captions, which have reliable
            timing data but little-to-no punctuation.

          Tier 2 — Punctuation splitting (fallback when segments unavailable).
            Splits flat text on [.!?]+.  Oversized chunks (> max_sentence_words)
            are re-split into fixed-size word-count windows so they are never
            silently dropped.

          Tier 3 — Word-count windowing (final fallback).
            Applied to any remaining oversized pieces from Tier 2.
        """
        raw_segments = raw_segments or {}
        sentences = []

        for video_id, text in transcripts.items():
            title = video_titles.get(video_id, f"Video {video_id[:8]}")
            segs = raw_segments.get(video_id)

            if segs:
                # ── Tier 1: segment-boundary chunking ─────────────────────────
                chunks = self._chunk_segments_boundary_aware(segs, video_id, title)
                sentences.extend(chunks)
                print(
                    f"[Fusion] {video_id}: {len(segs)} segments → "
                    f"{len(chunks)} chunks (segment-boundary)"
                )
            else:
                # ── Tier 2 + 3: punctuation split with word-count fallback ────
                raw_pieces = re.split(r'[.!?]+', text)
                added = 0
                for i, piece in enumerate(raw_pieces):
                    piece = piece.strip()
                    if not piece:
                        continue
                    words = piece.split()

                    if len(words) <= self.max_sentence_words:
                        if len(words) >= self.min_sentence_words:
                            sentences.append(SourcedSentence(
                                text=piece,
                                video_id=video_id,
                                video_title=title,
                                position=i,
                            ))
                            added += 1
                    else:
                        # ── Tier 3: word-count window for oversized piece ──
                        sub_chunks = self._wordcount_chunk(piece, video_id, title, i)
                        sentences.extend(sub_chunks)
                        added += len(sub_chunks)

                print(
                    f"[Fusion] {video_id}: punctuation-split → {added} chunks"
                )

        return sentences

    # ------------------------------------------------------------------
    # SENTENCE RECONSTRUCTION HELPERS
    # ------------------------------------------------------------------

    def _chunk_segments_boundary_aware(
        self,
        segments: list,
        video_id: str,
        video_title: str,
    ) -> List[SourcedSentence]:
        """
        Convert timestamped caption segments into fusion-ready chunks.

        Flush triggers (in priority order):
          1. Current segment ends with sentence-ending punctuation.
          2. Accumulated words >= TARGET_CHUNK_WORDS AND gap to next
             segment >= PAUSE_THRESHOLD_S (a meaningful speaker pause).
          3. Accumulated words >= max_sentence_words (hard cap — ensures no
             chunk is ever filtered by the downstream word-limit guard).
          4. Last segment in the transcript.

        Short remainders (< min_sentence_words) are merged into the
        previous chunk rather than silently discarded.
        """
        _sent_end = re.compile(r'[.!?]["\']?\s*$')

        chunks: List[SourcedSentence] = []
        buf_segs: list = []
        buf_words: int = 0
        chunk_idx: int = 0

        def _flush() -> None:
            nonlocal buf_segs, buf_words, chunk_idx
            if not buf_segs:
                return
            text = " ".join(s.get("text", "").strip() for s in buf_segs).strip()
            if text and len(text.split()) >= self.min_sentence_words:
                chunks.append(SourcedSentence(
                    text=text,
                    video_id=video_id,
                    video_title=video_title,
                    position=chunk_idx,
                ))
                chunk_idx += 1
            buf_segs = []
            buf_words = 0

        for i, seg in enumerate(segments):
            raw_text = seg.get("text", "").strip()
            if not raw_text:
                continue

            seg_word_count = len(raw_text.split())

            # Pre-flush: adding this segment would exceed the hard cap.
            if buf_words > 0 and buf_words + seg_word_count > self.max_sentence_words:
                _flush()

            # Single-segment overflow: the segment itself exceeds the hard cap
            # (e.g. a corrupt caption that swallowed many lines).  Split it
            # into word-count windows so the cap invariant is never violated.
            if seg_word_count > self.max_sentence_words:
                for sub in self._wordcount_chunk(raw_text, video_id, video_title, chunk_idx):
                    chunks.append(SourcedSentence(
                        text=sub.text,
                        video_id=video_id,
                        video_title=video_title,
                        position=chunk_idx,
                    ))
                    chunk_idx += 1
                continue  # segment handled; skip the normal accumulation path

            buf_segs.append(seg)
            buf_words += seg_word_count

            # Gap to next segment (0.0 if this is the last one)
            gap_s = 0.0
            if i + 1 < len(segments):
                seg_end = (
                    float(seg.get("start", 0.0))
                    + float(seg.get("duration", 0.0))
                )
                next_start = float(segments[i + 1].get("start", seg_end))
                gap_s = max(0.0, next_start - seg_end)

            ends_with_punct = bool(_sent_end.search(raw_text))
            is_last = (i == len(segments) - 1)

            should_flush = (
                ends_with_punct
                or (buf_words >= self.TARGET_CHUNK_WORDS and gap_s >= self.PAUSE_THRESHOLD_S)
                or buf_words >= self.max_sentence_words
                or is_last
            )

            if should_flush:
                if buf_words >= self.min_sentence_words:
                    _flush()
                elif buf_words >= self.max_sentence_words:
                    # Force-flush even if short — better than an infinite loop.
                    _flush()
                # else: keep accumulating — too short to stand alone.

        # Anything left over that never reached min_sentence_words:
        # merge into the last chunk rather than discarding.
        if buf_segs:
            leftover = " ".join(
                s.get("text", "").strip() for s in buf_segs
            ).strip()
            if leftover:
                if chunks:
                    last = chunks[-1]
                    chunks[-1] = SourcedSentence(
                        text=last.text + " " + leftover,
                        video_id=last.video_id,
                        video_title=last.video_title,
                        position=last.position,
                    )
                else:
                    # Entire transcript was too short — keep it as one unit.
                    chunks.append(SourcedSentence(
                        text=leftover,
                        video_id=video_id,
                        video_title=video_title,
                        position=0,
                    ))

        return chunks

    def _wordcount_chunk(
        self,
        text: str,
        video_id: str,
        video_title: str,
        base_position: int,
    ) -> List[SourcedSentence]:
        """
        Split an oversized text piece into max_sentence_words-sized windows.

        Used as Tier 3 fallback when punctuation splitting produces a chunk
        that still exceeds max_sentence_words (e.g. a flat text with no
        punctuation and no segment boundaries available).
        """
        words = text.split()
        results = []
        step = self.max_sentence_words  # non-overlapping windows
        sub_idx = 0
        for start in range(0, len(words), step):
            window = " ".join(words[start: start + step])
            if len(window.split()) >= self.min_sentence_words:
                results.append(SourcedSentence(
                    text=window,
                    video_id=video_id,
                    video_title=video_title,
                    position=base_position * 1000 + sub_idx,
                ))
                sub_idx += 1
        return results

    def _cluster_sentences(
        self,
        sentences: List[SourcedSentence],
        embeddings: np.ndarray
    ) -> List[TopicCluster]:
        """Cluster sentences by semantic similarity."""
        from sklearn.cluster import AgglomerativeClustering

        # Determine optimal number of clusters
        n_samples = len(sentences)
        n_clusters = max(3, min(n_samples // 5, 20))  # 3-20 clusters

        clustering = AgglomerativeClustering(
            n_clusters=n_clusters,
            metric='cosine',
            linkage='average'
        )

        labels = clustering.fit_predict(embeddings)

        # Group sentences by cluster
        cluster_dict = defaultdict(list)
        for i, label in enumerate(labels):
            cluster_dict[label].append(sentences[i])

        # Create TopicCluster objects
        clusters = []
        for cluster_id, sents in cluster_dict.items():
            # Calculate centroid
            cluster_embeddings = np.array([s.embedding for s in sents])
            centroid = np.mean(cluster_embeddings, axis=0)

            # Find representative sentence (closest to centroid)
            distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
            rep_idx = np.argmin(distances)
            representative = sents[rep_idx].text

            # Get unique source videos
            source_videos = list(set(s.video_id for s in sents))

            # Generate topic label (first few words of representative)
            topic_label = " ".join(representative.split()[:5]) + "..."

            # Calculate importance (more sources + more sentences = more important)
            importance = len(sents) * len(source_videos)

            clusters.append(TopicCluster(
                cluster_id=cluster_id,
                sentences=sents,
                centroid=centroid,
                representative=representative,
                source_videos=source_videos,
                topic_label=topic_label,
                importance_score=importance
            ))

        # Sort by importance
        clusters.sort(key=lambda c: c.importance_score, reverse=True)

        return clusters

    def _deduplicate_clusters(
        self,
        clusters: List[TopicCluster]
    ) -> List[TopicCluster]:
        """Remove redundant sentences within clusters."""
        deduplicated = []

        for cluster in clusters:
            if len(cluster.sentences) <= 1:
                deduplicated.append(cluster)
                continue

            # Keep only unique-enough sentences
            kept = [cluster.sentences[0]]
            kept_embeddings = [cluster.sentences[0].embedding]

            for sent in cluster.sentences[1:]:
                # Check similarity to all kept sentences
                similarities = [
                    np.dot(sent.embedding, e) / (np.linalg.norm(sent.embedding) * np.linalg.norm(e))
                    for e in kept_embeddings
                ]
                max_sim = max(similarities)

                # Keep if different enough
                if max_sim < self.similarity_threshold:
                    kept.append(sent)
                    kept_embeddings.append(sent.embedding)

            # Update cluster
            cluster.sentences = kept
            deduplicated.append(cluster)

        return deduplicated

    def _validate_selected_evidence_narrative(
        self,
        ordered_sentences: List[SourcedSentence],
    ) -> None:
        """Selected-evidence narratives must stay in canonical order."""
        if not ordered_sentences:
            return
        positions = [s.manifest_position for s in ordered_sentences]
        if positions != sorted(positions):
            raise ValueError("surviving evidence positions are not strictly increasing")

    def _synthesize_selected_evidence(
        self,
        ordered_sentences: List[SourcedSentence],
        target_words: int,
        include_sources: bool,
        include_transitions: bool,
    ) -> str:
        """Serialize selected evidence in canonical manifest order."""
        if not ordered_sentences:
            return ""

        transition_phrases = [
            "Additionally,",
            "Furthermore,",
            "Moreover,",
            "In related terms,",
        ]

        parts = []
        for idx, sentence in enumerate(ordered_sentences):
            text = sentence.text.strip()
            if not text:
                continue
            if include_sources and sentence.video_id:
                text = f"{text} (from {sentence.video_id})"
            if idx > 0 and include_transitions:
                text = f"{transition_phrases[(idx - 1) % len(transition_phrases)]} {text}"
            parts.append(text)

        narrative = " ".join(parts)
        last_index = -1
        for sentence in ordered_sentences:
            marker = sentence.text.strip()
            if not marker:
                continue
            index = narrative.find(marker)
            if index < 0:
                raise ValueError(f"selected evidence marker missing from narrative: {marker}")
            if index < last_index:
                raise ValueError("selected evidence narrative order does not match canonical surviving manifest order")
            last_index = index
        return narrative

    def _detect_conflicts(
        self,
        clusters: List[TopicCluster]
    ) -> List[ConflictPoint]:
        """
        Detect disagreements between sources using NLI (Natural Language Inference).
        Falls back to keyword-based detection if NLI model is unavailable.
        """
        try:
            return self._detect_conflicts_nli(clusters)
        except Exception as e:
            print(f"[Fusion] NLI conflict detection failed ({e}), falling back to keyword method")
            return self._detect_conflicts_keyword(clusters)

    def _detect_conflicts_nli(
        self,
        clusters: List[TopicCluster]
    ) -> List[ConflictPoint]:
        """
        NLI-based conflict detection using cross-encoder/nli-deberta-v3-small.
        Detects actual semantic contradictions between video sources.
        """
        from transformers import pipeline as hf_pipeline
        from ..core.config import get_hf_token

        # Lazy load NLI model (140MB, runs on CPU)
        if not hasattr(self, '_nli_pipeline') or self._nli_pipeline is None:
            print("[Fusion] Loading NLI model: cross-encoder/nli-deberta-v3-small")
            self._nli_pipeline = hf_pipeline(
                "text-classification",
                model="cross-encoder/nli-deberta-v3-small",
                token=get_hf_token(),  # None when unset → anonymous, same as before
            )
            print("[Fusion] NLI model loaded")

        conflicts = []
        for cluster in clusters:
            if len(cluster.source_videos) < 2:
                continue

            # Group statements by video
            video_statements = defaultdict(list)
            for sent in cluster.sentences:
                video_statements[sent.video_id].append(sent.text)

            # Compare statements across video pairs
            video_ids = list(video_statements.keys())
            for i in range(len(video_ids)):
                for j in range(i + 1, len(video_ids)):
                    # Take first 2 statements from each video
                    stmt_a = " ".join(video_statements[video_ids[i]][:2])[:512]
                    stmt_b = " ".join(video_statements[video_ids[j]][:2])[:512]

                    if not stmt_a.strip() or not stmt_b.strip():
                        continue

                    # Run NLI classification
                    try:
                        result = self._nli_pipeline(
                            f"{stmt_a} [SEP] {stmt_b}",
                            truncation=True,
                        )
                        label = result[0]["label"].upper()
                        score = result[0]["score"]

                        if "CONTRADICTION" in label and score > 0.7:
                            conflicts.append(ConflictPoint(
                                topic=cluster.topic_label,
                                positions={
                                    video_ids[i]: f"States: {stmt_a[:120]}...",
                                    video_ids[j]: f"States: {stmt_b[:120]}...",
                                },
                                confidence=round(score, 3),
                                resolution_strategy="present_both_perspectives",
                            ))
                    except Exception:
                        continue

        return conflicts

    def _detect_conflicts_keyword(
        self,
        clusters: List[TopicCluster]
    ) -> List[ConflictPoint]:
        """Fallback: keyword-based conflict detection."""
        conflicts = []

        negative_indicators = [
            "not", "never", "wrong", "false", "incorrect", "disagree",
            "however", "but", "although", "contrary", "opposite"
        ]
        positive_indicators = [
            "is", "are", "will", "should", "must", "always", "definitely"
        ]

        for cluster in clusters:
            if len(cluster.source_videos) < 2:
                continue

            video_statements = defaultdict(list)
            for sent in cluster.sentences:
                video_statements[sent.video_id].append(sent.text)

            positions = {}
            for video_id, statements in video_statements.items():
                combined = " ".join(statements).lower()
                neg_count = sum(1 for w in negative_indicators if w in combined)
                pos_count = sum(1 for w in positive_indicators if w in combined)

                if neg_count > pos_count:
                    positions[video_id] = "disagrees/negative"
                else:
                    positions[video_id] = "agrees/positive"

            unique_positions = set(positions.values())
            if len(unique_positions) > 1:
                conflicts.append(ConflictPoint(
                    topic=cluster.topic_label,
                    positions={vid: f"{pos}: {video_statements[vid][0][:100]}..."
                              for vid, pos in positions.items()},
                    confidence=0.6,
                    resolution_strategy="present_all"
                ))

        return conflicts

    def _synthesize_narrative(
        self,
        clusters: List[TopicCluster],
        conflicts: List[ConflictPoint],
        target_words: int,
        include_sources: bool,
        include_transitions: bool
    ) -> str:
        """Create coherent narrative from clustered content."""
        narrative_parts = []
        current_words = 0
        transition_phrases = [
            "Additionally,",
            "Furthermore,",
            "Moreover,",
            "In related terms,",
            "Building on this,",
            "Another key point is that",
            "It's also worth noting that",
            "Expanding on this idea,"
        ]
        transition_idx = 0

        for i, cluster in enumerate(clusters):
            if current_words >= target_words:
                break

            # Get representative content from cluster
            content = self._get_cluster_summary(cluster, include_sources)

            # Add transition for non-first paragraphs
            if i > 0 and include_transitions:
                content = f"{transition_phrases[transition_idx % len(transition_phrases)]} {content}"
                transition_idx += 1

            # Check if adding this would exceed target (always allow first cluster to prevent empty narrative)
            content_words = len(content.split())
            if current_words == 0 or current_words + content_words <= target_words * 1.1:  # 10% buffer
                narrative_parts.append(content)
                current_words += content_words

        # Add conflict notes if any
        if conflicts and current_words < target_words:
            conflict_note = self._format_conflicts(conflicts)
            narrative_parts.append(conflict_note)

        return "\n\n".join(narrative_parts)

    def _get_cluster_summary(
        self,
        cluster: TopicCluster,
        include_sources: bool
    ) -> str:
        """Get summary text for a cluster."""
        # Use representative + supporting sentences
        parts = [cluster.representative]

        # Add 2-4 supporting sentences for richer detail
        for sent in cluster.sentences[1:5]:
            if sent.text != cluster.representative:
                parts.append(sent.text)

        summary = ". ".join(parts)

        # Add source attribution
        if include_sources and len(cluster.source_videos) > 1:
            summary += f" (discussed in {len(cluster.source_videos)} videos)"

        return summary

    def _format_conflicts(self, conflicts: List[ConflictPoint]) -> str:
        """Format conflict information for narrative."""
        if not conflicts:
            return ""

        notes = ["Note: Some sources had differing perspectives:"]
        for conflict in conflicts[:3]:  # Max 3 conflicts
            notes.append(f"- On '{conflict.topic}': sources presented varying viewpoints")

        return " ".join(notes)


# =====================================================
# SINGLETON INSTANCE
# =====================================================

_fusion_engine = None


def get_fusion_engine() -> FusionEngine:
    """Get singleton fusion engine instance."""
    global _fusion_engine
    if _fusion_engine is None:
        _fusion_engine = FusionEngine()
    return _fusion_engine
