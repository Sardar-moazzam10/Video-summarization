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
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime
import numpy as np
import re
from collections import defaultdict

# Lazy imports for heavy libraries
_sentence_transformer = None
_clustering_model = None


def get_sentence_transformer():
    """Lazy load sentence transformer model."""
    global _sentence_transformer
    if _sentence_transformer is None:
        from sentence_transformers import SentenceTransformer
        _sentence_transformer = SentenceTransformer('all-MiniLM-L6-v2')
        print("[OK] Loaded Sentence-BERT model: all-MiniLM-L6-v2")
    return _sentence_transformer


@dataclass
class SourcedSentence:
    """A sentence with its source video tracking."""
    text: str
    video_id: str
    video_title: str = ""
    position: int = 0  # Position in original transcript
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
        include_transitions: bool = True
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

        # Step 1: Extract sentences with source tracking
        print(f"[Fusion] Processing {len(transcripts)} transcripts...")
        sentences = self._extract_sentences(transcripts, video_titles)
        print(f"[Fusion] Extracted {len(sentences)} sentences")

        if len(sentences) < 3:
            return FusionResult(
                narrative=" ".join([s.text for s in sentences]),
                topics=[],
                conflicts=[],
                metadata={"error": "Too few sentences to fuse"}
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

        # Step 5: Detect conflicts
        conflicts = self._detect_conflicts(deduplicated)
        print(f"[Fusion] Found {len(conflicts)} potential conflicts")

        # Step 6: Synthesize narrative
        narrative = self._synthesize_narrative(
            deduplicated,
            conflicts,
            target_words,
            include_sources,
            include_transitions
        )

        # Calculate metadata
        total_source_words = sum(len(t.split()) for t in transcripts.values())
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
            "videos_processed": len(transcripts)
        }

        return FusionResult(
            narrative=narrative,
            topics=topics,
            conflicts=conflicts,
            metadata=metadata
        )

    def _extract_sentences(
        self,
        transcripts: Dict[str, str],
        video_titles: Dict[str, str]
    ) -> List[SourcedSentence]:
        """Extract and clean sentences from all transcripts."""
        sentences = []

        for video_id, text in transcripts.items():
            title = video_titles.get(video_id, f"Video {video_id[:8]}")
            # Split into sentences
            raw_sentences = re.split(r'[.!?]+', text)

            for i, sent in enumerate(raw_sentences):
                sent = sent.strip()
                words = sent.split()

                # Filter by length
                if self.min_sentence_words <= len(words) <= self.max_sentence_words:
                    sentences.append(SourcedSentence(
                        text=sent,
                        video_id=video_id,
                        video_title=title,
                        position=i
                    ))

        return sentences

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

        # Lazy load NLI model (140MB, runs on CPU)
        if not hasattr(self, '_nli_pipeline') or self._nli_pipeline is None:
            print("[Fusion] Loading NLI model: cross-encoder/nli-deberta-v3-small")
            self._nli_pipeline = hf_pipeline(
                "text-classification",
                model="cross-encoder/nli-deberta-v3-small",
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

            # Check if adding this would exceed target
            content_words = len(content.split())
            if current_words + content_words <= target_words * 1.1:  # 10% buffer
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
