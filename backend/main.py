"""
Video Summarizer API - FastAPI Main Application

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
    # Check Gemini availability
    try:
        from .services.gemini_service import get_gemini_service
        gemini = get_gemini_service()
        if gemini.is_available():
            print(f"[OK] Gemini AI: configured (text: {settings.GEMINI_MODEL}, video: {settings.GEMINI_VIDEO_MODEL})")
        else:
            print("[INFO] Gemini AI: not configured (BART fallback active)")
    except Exception as e:
        print(f"[WARN] Gemini check failed: {e}")
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

# CORS - Allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS + ["*"],
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
app.include_router(chat.router)  # Chat with video (FAISS + Gemini)


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
