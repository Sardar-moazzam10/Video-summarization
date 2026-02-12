"""
Semantic Search API - FAISS-powered natural language search

Endpoints:
- GET /api/v1/search?q=<query>&top_k=10 - Semantic search across all transcripts
- GET /api/v1/search/stats - Index statistics
"""

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.get("")
async def semantic_search(
    q: str = Query(..., description="Natural language search query", min_length=2),
    top_k: int = Query(default=10, ge=1, le=50, description="Number of results"),
):
    """
    Semantic search across all previously processed video transcripts.

    Uses FAISS vector store with all-MiniLM-L6-v2 embeddings for
    meaning-based search (not keyword matching).
    """
    try:
        from ..services.vector_store import get_vector_store
        store = get_vector_store()
    except ImportError:
        raise HTTPException(
            501,
            "FAISS not installed. Run: pip install faiss-cpu"
        )

    if store.index.ntotal == 0:
        return {
            "query": q,
            "results": [],
            "total": 0,
            "message": "No transcripts indexed yet. Process some videos first.",
        }

    results = store.search(q, top_k=top_k)

    return {
        "query": q,
        "results": results,
        "total": len(results),
    }


@router.get("/stats")
async def search_stats():
    """Get statistics about the semantic search index."""
    try:
        from ..services.vector_store import get_vector_store
        store = get_vector_store()
        return store.get_stats()
    except ImportError:
        return {"error": "FAISS not installed"}
