"""
FAISS Vector Store - Semantic search across all processed transcripts

Stores sentence embeddings in a FAISS index for fast similarity search.
Enables "search by meaning" — users can type natural language queries
and find relevant sections across all previously processed videos.

Uses the same all-MiniLM-L6-v2 embedder as the fusion engine.
"""

import numpy as np
import pickle
from pathlib import Path
from typing import Optional, List, Dict, Any

# Lazy-loaded
_embedder = None
_vector_store = None


def _get_embedder():
    """Reuse the same embedder as the fusion engine."""
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        print("[VectorStore] Loaded embedder: all-MiniLM-L6-v2")
    return _embedder


class VectorStore:
    """
    FAISS-based vector store for semantic search across transcripts.

    Features:
    - Cosine similarity search (normalized inner product)
    - Persistent index on disk
    - Metadata tracking (video_id, video_title, text, timestamp)
    - Deduplication by video_id
    """

    DIMENSION = 384  # all-MiniLM-L6-v2 output dimension

    def __init__(self, index_dir: str = "faiss_index"):
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(exist_ok=True)
        self.index = None
        self.metadata: List[Dict[str, Any]] = []
        self._indexed_videos: set = set()
        self._load_or_create()

    def _load_or_create(self):
        """Load existing index from disk or create a new one."""
        import faiss

        idx_file = self.index_dir / "index.faiss"
        meta_file = self.index_dir / "metadata.pkl"

        if idx_file.exists() and meta_file.exists():
            try:
                self.index = faiss.read_index(str(idx_file))
                with open(meta_file, "rb") as f:
                    data = pickle.load(f)
                self.metadata = data.get("metadata", [])
                self._indexed_videos = data.get("indexed_videos", set())
                print(f"[VectorStore] Loaded index: {self.index.ntotal} vectors, {len(self._indexed_videos)} videos")
            except Exception as e:
                print(f"[VectorStore] Failed to load index, creating new: {e}")
                self.index = faiss.IndexFlatIP(self.DIMENSION)
                self.metadata = []
                self._indexed_videos = set()
        else:
            self.index = faiss.IndexFlatIP(self.DIMENSION)
            self.metadata = []
            self._indexed_videos = set()
            print("[VectorStore] Created new empty index")

    def _save(self):
        """Persist index and metadata to disk."""
        import faiss

        faiss.write_index(self.index, str(self.index_dir / "index.faiss"))
        with open(self.index_dir / "metadata.pkl", "wb") as f:
            pickle.dump({
                "metadata": self.metadata,
                "indexed_videos": self._indexed_videos,
            }, f)

    def is_video_indexed(self, video_id: str) -> bool:
        """Check if a video has already been indexed."""
        return video_id in self._indexed_videos

    def add_transcript(
        self,
        video_id: str,
        video_title: str,
        transcript_text: str,
    ) -> int:
        """
        Index a transcript's sentences into the vector store.

        Args:
            video_id: YouTube video ID
            video_title: Human-readable title
            transcript_text: Full transcript text

        Returns:
            Number of sentences indexed
        """
        import faiss

        if self.is_video_indexed(video_id):
            return 0

        # Split into sentences
        sentences = self._split_into_sentences(transcript_text)
        if not sentences:
            return 0

        # Generate embeddings
        embedder = _get_embedder()
        embeddings = embedder.encode(sentences, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype="float32")

        # Normalize for cosine similarity (IndexFlatIP)
        faiss.normalize_L2(embeddings)

        # Add to index
        self.index.add(embeddings)

        # Track metadata
        for i, sent in enumerate(sentences):
            self.metadata.append({
                "text": sent,
                "video_id": video_id,
                "video_title": video_title,
                "sentence_index": i,
            })

        self._indexed_videos.add(video_id)
        self._save()

        print(f"[VectorStore] Indexed {len(sentences)} sentences from {video_id}")
        return len(sentences)

    def add_transcript_with_timestamps(
        self,
        video_id: str,
        video_title: str,
        segments: list,
    ) -> int:
        """
        Index transcript segments preserving timestamps.

        Args:
            video_id: YouTube video ID
            video_title: Human-readable title
            segments: List of {text, start, duration} dicts

        Returns:
            Number of segments indexed
        """
        import faiss

        if self.is_video_indexed(video_id):
            return 0

        # Filter segments with meaningful text (at least 3 words)
        valid_segments = [
            seg for seg in segments
            if len(seg.get("text", "").strip().split()) >= 3
        ]

        if not valid_segments:
            return 0

        texts = [seg["text"].strip() for seg in valid_segments]
        timestamps = [float(seg.get("start", 0)) for seg in valid_segments]

        # Generate embeddings
        embedder = _get_embedder()
        embeddings = embedder.encode(texts, show_progress_bar=False)
        embeddings = np.array(embeddings, dtype="float32")

        # Normalize for cosine similarity
        faiss.normalize_L2(embeddings)

        # Add to index
        self.index.add(embeddings)

        # Track metadata with timestamps
        for i, (text, ts) in enumerate(zip(texts, timestamps)):
            self.metadata.append({
                "text": text,
                "video_id": video_id,
                "video_title": video_title,
                "timestamp": ts,
                "sentence_index": i,
            })

        self._indexed_videos.add(video_id)
        self._save()

        print(f"[VectorStore] Indexed {len(texts)} segments with timestamps from {video_id}")
        return len(texts)

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        Semantic search across all indexed transcripts.

        Args:
            query: Natural language search query
            top_k: Number of results to return

        Returns:
            List of results with text, video_id, video_title, score
        """
        import faiss

        if self.index.ntotal == 0:
            return []

        embedder = _get_embedder()
        query_emb = embedder.encode([query], show_progress_bar=False)
        query_emb = np.array(query_emb, dtype="float32")
        faiss.normalize_L2(query_emb)

        # Search
        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_emb, k)

        results = []
        seen_texts = set()  # Deduplicate similar results
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.metadata):
                continue
            meta = self.metadata[idx]
            # Skip near-duplicate texts
            text_key = meta["text"][:80].lower()
            if text_key in seen_texts:
                continue
            seen_texts.add(text_key)

            results.append({
                "text": meta["text"],
                "video_id": meta["video_id"],
                "video_title": meta["video_title"],
                "score": round(float(score), 4),
            })

        return results

    def get_stats(self) -> dict:
        """Get index statistics."""
        return {
            "total_vectors": self.index.ntotal if self.index else 0,
            "total_videos": len(self._indexed_videos),
            "video_ids": list(self._indexed_videos),
        }

    @staticmethod
    def _split_into_sentences(text: str) -> List[str]:
        """Split text into meaningful sentences for indexing."""
        import re
        # Split on sentence boundaries
        raw = re.split(r'(?<=[.!?])\s+', text)
        # Filter: keep sentences with at least 5 words
        return [s.strip() for s in raw if len(s.strip().split()) >= 5]


def get_vector_store() -> VectorStore:
    """Get singleton vector store instance."""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
