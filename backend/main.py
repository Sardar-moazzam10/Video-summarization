import os
# Suppress HuggingFace Hub "unauthenticated requests" warning — models are cached locally
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_VERBOSITY", "error")

"""
VidFusion API - FastAPI Main Application

Single unified backend replacing:
- auth_backend.py (port 5000)
- transcript_backend.py (port 5001)
- merge_backend.py (port 5002)

Now all in ONE clean FastAPI app.

Run with:
    uvicorn backend.main:app --reload --port 8000
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from collections import defaultdict
import time

from .core.config import get_settings
from .core.database import close_database
from .api import auth, transcript, merge, voice, search, chat

settings = get_settings()

# Simple in-memory rate limiter
rate_limit_store: dict = defaultdict(list)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    print(f"[OK] {settings.APP_NAME} starting...")
    # Pre-load AI models to eliminate cold start on first merge
    try:
        from .services.summarization_service import _get_pipeline
        _get_pipeline()
        print("[OK] BART summarization model pre-loaded")
    except Exception as e:
        print(f"[WARN] Could not pre-load summarization model: {e}")
    try:
        from .services.fusion_engine import get_sentence_transformer
        get_sentence_transformer()
        print("[OK] Sentence-BERT embedding model pre-loaded")
    except Exception as e:
        print(f"[WARN] Could not pre-load embedding model: {e}")

    # FAISS dimension guard: clear index if it contains an unrecognised embedding dimension.
    # VectorStore._load_or_create() also checks this at runtime, but this guard runs first.
    try:
        import pickle as _pickle, shutil as _shutil
        from pathlib import Path as _Path
        _faiss_dir = _Path("faiss_index")
        if _faiss_dir.exists():
            _meta_path = _faiss_dir / "metadata.pkl"
            if _meta_path.exists():
                _meta = _pickle.load(open(_meta_path, "rb"))
                # embedding_dim is stored in metadata; 384 is correct for MiniLM
                _stored_dim = _meta.get("embedding_dim", 384)
                # Accept 384 (MiniLM), 768 (BGE), and 0 (legacy, no dim saved)
                if _stored_dim not in (384, 768, 0):
                    _shutil.rmtree(_faiss_dir)
                    print(f"[WARN] FAISS index cleared: unexpected embedding_dim={_stored_dim}")
    except Exception as e:
        print(f"[WARN] FAISS dimension check failed: {e}")

    # Check Ollama availability
    try:
        from .services.ollama_service import get_ollama_service
        ollama = get_ollama_service()
        if ollama.is_available():
            print(f"[OK] Ollama LLM: ready — model: {settings.OLLAMA_MODEL}")
        else:
            print(f"[INFO] Ollama: not available — TF-IDF fallback active\n"
                  f"       Run: ollama pull {settings.OLLAMA_MODEL}")
    except Exception as e:
        print(f"[WARN] Ollama check failed: {e}")

    # Audio energy scorer uses ffmpeg + librosa — no model download, no pre-load needed.

    yield
    # Shutdown
    await close_database()
    print("[OK] Shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered YouTube video summarization API",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS - explicit origins + regex to cover any localhost/127.0.0.1 port
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple rate limiting: 60 requests per minute per IP"""
    client_ip = request.client.host if request.client else "unknown"
    current_time = time.time()
    window_start = current_time - 60  # 1 minute window

    # Clean old entries
    rate_limit_store[client_ip] = [
        t for t in rate_limit_store[client_ip] if t > window_start
    ]

    # Check limit
    if len(rate_limit_store[client_ip]) >= settings.RATE_LIMIT_PER_MINUTE:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please wait a minute."}
        )

    # Record request
    rate_limit_store[client_ip].append(current_time)

    return await call_next(request)


# Include routers
app.include_router(auth.router)
app.include_router(transcript.router)
app.include_router(merge.router)
app.include_router(voice.router)  # FREE Edge TTS
app.include_router(search.router)  # FAISS semantic search
app.include_router(chat.router)  # Chat with video (FAISS + Ollama)


@app.get("/")
async def root():
    """API root endpoint"""
    return {
        "name": settings.APP_NAME,
        "version": "2.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy"}


# ===== Run directly =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
