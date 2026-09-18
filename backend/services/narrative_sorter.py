import numpy as np
from typing import List, Any
import logging

logger = logging.getLogger(__name__)

def sort_segments(segments: List[Any], embedder=None) -> List[Any]:
    """
    Sort segments narratively rather than by video_id.
    1. Cluster segments into topics.
    2. Order clusters logically.
    3. Pair conflicting segments (NLI).
    """
    if not segments:
        return segments

    try:
        from .fusion_engine import get_sentence_transformer
        from sentence_transformers import CrossEncoder
        if embedder is None:
            embedder = get_sentence_transformer()
    except ImportError:
        logger.warning("[Narrative] SentenceTransformer not available, falling back to chronological sort")
        segments.sort(key=lambda s: getattr(s, "start_time", 0.0))
        return segments

    # 1. Embed and cluster
    texts = [getattr(s, "text", "") for s in segments]
    try:
        embeddings = embedder.encode(texts, show_progress_bar=False)
    except Exception as e:
        logger.warning(f"[Narrative] Embedding failed: {e}")
        segments.sort(key=lambda s: getattr(s, "start_time", 0.0))
        return segments

    # We use a simple K-Means or hierarchical clustering.
    # For small N, agglomerative is easy.
    from sklearn.cluster import AgglomerativeClustering
    n_clusters = max(1, min(len(segments) // 2, 7))
    if len(segments) < 3:
        n_clusters = 1
        
    clusterer = AgglomerativeClustering(
        n_clusters=n_clusters, 
        metric='cosine', 
        linkage='average'
    )
    labels = clusterer.fit_predict(embeddings)
    
    clusters = {i: [] for i in range(n_clusters)}
    for i, label in enumerate(labels):
        clusters[label].append((i, segments[i]))
        
    # Order clusters by their median relative timestamp
    cluster_scores = {}
    for label, items in clusters.items():
        # Relative time: start_time / total_video_duration (assumed 1.0 if not available)
        times = [item[1].start_time for item in items]
        cluster_scores[label] = np.median(times)
        
    ordered_labels = sorted(clusters.keys(), key=lambda l: cluster_scores[l])
    
    final_segments = []
    
    # Attempt to load NLI for conflict detection
    nli_model = None
    try:
        nli_model = CrossEncoder('cross-encoder/nli-deberta-v3-small')
        logger.info("[Narrative] Loaded NLI model for ordering")
    except Exception as e:
        logger.info(f"[Narrative] NLI model unavailable for ordering: {e}")

    for label in ordered_labels:
        cluster_items = clusters[label]
        # Sort items chronologically within the cluster as a baseline
        cluster_items.sort(key=lambda x: x[1].start_time)
        
        if nli_model and len(cluster_items) > 1:
            # Pair them up based on NLI
            # Very simple pairing: if i and j contradict, place j immediately after i
            placed = set()
            paired_seq = []
            
            for idx in range(len(cluster_items)):
                if idx in placed:
                    continue
                placed.add(idx)
                paired_seq.append(cluster_items[idx][1])
                
                # Look for a contradiction to pair with
                for jdx in range(idx + 1, len(cluster_items)):
                    if jdx in placed:
                        continue
                    
                    try:
                        scores = nli_model.predict([(cluster_items[idx][1].text, cluster_items[jdx][1].text)])
                        # scores = [contradiction, entailment, neutral]
                        if scores[0][0] > max(scores[0][1], scores[0][2]):
                            # Contradiction! Place immediately after to show alternative viewpoint
                            placed.add(jdx)
                            paired_seq.append(cluster_items[jdx][1])
                            logger.info("[Narrative] Placed contradiction adjacently!")
                            break
                    except Exception:
                        pass
                        
            final_segments.extend(paired_seq)
        else:
            final_segments.extend([item[1] for item in cluster_items])

    return final_segments
