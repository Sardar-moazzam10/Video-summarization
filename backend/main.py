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
from .core.redis_queue import init_redis_pool, close_redis_pool
from .api import auth, transcript, merge, search, chat, youtube, rights

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

    # Audio energy scorer uses ffmpeg + librosa — no model download, no pre-load needed.
    # Source rights compound index initialization (user_id, source_type, source_id)
    try:
        from .services.rights_service import ensure_rights_indexes
        await ensure_rights_indexes()
        print("[OK] Source rights MongoDB compound indexes verified")
    except Exception as e:
        print(f"[WARN] Could not initialize source rights indexes: {e}")

    # ACQ-M1A shadow-observability indexes. Failure is visible but fail-open:
    # acquisition telemetry must never prevent the legacy product from starting.
    try:
        from .services.acquisition_service import ensure_acquisition_indexes
        await ensure_acquisition_indexes()
        print("[OK] Acquisition shadow-observability indexes verified")
    except Exception as e:
        print(f"[WARN] Could not initialize acquisition indexes: {e}")

    try:
        from .core.database import get_database
        from .services.output_task_queue import (
            ensure_output_task_indexes,
            recover_expired_output_tasks,
            recover_prepared_output_dispatches,
        )
        db = await get_database()
        await ensure_output_task_indexes(db)
        recovered_dispatches = await recover_prepared_output_dispatches(db)
        recovered_tasks = await recover_expired_output_tasks(db)
        print(
            "[OK] Durable output-task indexes verified; "
            f"dispatches={recovered_dispatches}; leases={recovered_tasks}"
        )
    except Exception as e:
        print(f"[WARN] Could not initialize output-task indexes: {e}")

    # Process-local jobs are failed only after durable task ownership has been
    # recovered. Manifest-first jobs explicitly owned by output workers are
    # excluded by recover_orphaned_jobs.
    try:
        from .core.database import get_database
        from .services.job_recovery import recover_orphaned_jobs
        db = await get_database()
        recovery = await recover_orphaned_jobs(db["jobs"])
        print(f"[OK] Orphan recovery: {recovery}")
    except Exception as e:
        print(f"[WARN] Could not recover orphaned merge jobs: {e}")

    # Storage hygiene check on boot
    try:
        from .services.storage_hygiene import run_storage_hygiene
        import asyncio
        hygiene_report = await asyncio.to_thread(run_storage_hygiene)
        print(f"[OK] Storage hygiene on boot: {hygiene_report}")
    except Exception as e:
        print(f"[WARN] Storage hygiene initialization error: {e}")

    # Periodic background hygiene worker
    async def _periodic_hygiene():
        while True:
            try:
                await asyncio.sleep(3600)  # Every 1 hour
                from .services.storage_hygiene import run_storage_hygiene
                await asyncio.to_thread(run_storage_hygiene)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WARN] Periodic storage hygiene error: {e}")

    hygiene_task = asyncio.create_task(_periodic_hygiene())

    # Redis Queue pool initialization for async worker processing
    try:
        await init_redis_pool()
    except Exception as e:
        print(f"[WARN] Redis Queue initialization error: {e}")

    yield
    # Shutdown
    hygiene_task.cancel()
    await close_redis_pool()
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


def request_counts_toward_rate_limit(path: str, method: str) -> bool:
    """Polling/acquisition traffic has its own bounds and must not poison UI limits."""
    return not (
        path.startswith("/api/v1/merge/")
        or path.startswith("/api/v1/transcript/")
        or method == "OPTIONS"
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

    # Check limit - exclude status polling endpoints and merge progress from rate limiting
    is_polling = not request_counts_toward_rate_limit(request.url.path, request.method)
    if not is_polling and len(rate_limit_store[client_ip]) >= settings.RATE_LIMIT_PER_MINUTE:
        origin = request.headers.get("origin", "*")
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many requests. Please wait a minute."},
            headers={
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Credentials": "true",
            },
        )

    # Exempt traffic must not poison the counted window.
    if not is_polling:
        rate_limit_store[client_ip].append(current_time)

    try:
        return await call_next(request)
    except BaseException as e:
        import asyncio
        if isinstance(e, asyncio.CancelledError):
            return JSONResponse(status_code=499, content={"detail": "Client Closed Request"})
        raise


# Include routers
app.include_router(auth.router)
app.include_router(transcript.router)
app.include_router(merge.router)
app.include_router(search.router)  # FAISS semantic search
app.include_router(chat.router)  # Chat with video (FAISS + Ollama)
app.include_router(youtube.router)  # Public video-title/topic search
app.include_router(rights.router)  # Rights-aware provenance and gating


@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Health check"""
    return {"status": "healthy"}


# =====================================================
# SINGLE-PORT PRODUCTION SERVING (React SPA)
# =====================================================
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_frontend_dir = None
for _candidate in [Path("build"), Path("static")]:
    if _candidate.is_dir() and (_candidate / "index.html").is_file():
        _frontend_dir = _candidate
        break

if _frontend_dir:
    _static_dir = _frontend_dir / "static"
    if _static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static_assets")

    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_spa_root():
        return FileResponse(str(_frontend_dir / "index.html"))

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_spa_fallback(full_path: str):
        # Do not intercept API, health, docs, or schema routes
        if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json", "health"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        # Serve static assets located in the root of the build folder (e.g. favicon.ico, manifest.json)
        asset_file = _frontend_dir / full_path
        if asset_file.is_file():
            return FileResponse(str(asset_file))

        # Client-side routing fallback (SearchPage, MergedPlayer, History, etc.)
        return FileResponse(str(_frontend_dir / "index.html"))
else:
    @app.get("/")
    async def root():
        """API root endpoint (fallback when frontend build is not present)"""
        return {
            "name": settings.APP_NAME,
            "version": "2.0.0",
            "docs": "/docs",
            "status": "running"
        }


# ===== Run directly =====
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
