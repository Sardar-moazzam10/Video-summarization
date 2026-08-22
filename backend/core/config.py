"""
Core configuration - Single source of truth
Production-ready settings with security
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import List, Optional
import os
import secrets


class Settings(BaseSettings):
    # =====================================================
    # APP SETTINGS
    # =====================================================
    APP_NAME: str = "VidFusion"

    # =====================================================
    # SECURITY (CRITICAL)
    # =====================================================
    SECRET_KEY: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description="JWT signing key - MUST set in production"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000"
    ]

    # =====================================================
    # DATABASE
    # =====================================================
    MONGODB_URI: str = "mongodb://localhost:27017/"
    MONGODB_DATABASE: str = "video-summarizer"

    # =====================================================
    # EMAIL
    # =====================================================
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_PORT: int = 587
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""

    # =====================================================
    # LOCAL LLM (Ollama — free, no API key needed)
    # Install: https://ollama.com | then: ollama pull llama3.2:3b
    # =====================================================
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2:3b"      # 2 GB RAM; swap to mistral:7b or ministral:8b for better quality
    OLLAMA_TIMEOUT_SECONDS: float = 100.0  # httpx hard limit — must be < the 120s asyncio wrapper in merge.py so background threads terminate before the asyncio cancel fires

    # Ollama enrichment inside the MERGE pipeline only.
    # Disabled by default: on CPU, llama3.2:3b consistently exceeds the timeout
    # and returns nothing, so the job pays ~100s and then falls back to the local
    # TF-IDF enrichment anyway (see _generate_local_enrichment in api/merge.py).
    # Turning this off removes that dead time with no change to job output.
    # This flag does NOT affect the Quality Panel's LLM judge (/merge/{id}/evaluate
    # → evaluate_summary.ollama_judge), which calls Ollama directly and still works.
    # Set ENABLE_OLLAMA_ENRICHMENT=true in .env to re-enable (e.g. on a GPU machine).
    ENABLE_OLLAMA_ENRICHMENT: bool = False

    # =====================================================
    # AI/ML SETTINGS
    # =====================================================
    SUMMARIZATION_MODEL: str = "sshleifer/distilbart-cnn-12-6"  # 306 MB vs 1.6 GB BART-large, 95% quality
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"              # #1 MTEB 2024, 768-dim, replaces all-MiniLM
    CLIP_MODEL: str = "openai/clip-vit-base-patch16"            # ViT-B/16: 17% better than B/32, same API

    # Whisper size used by the transcript service, including its translate task
    # for non-English videos. Measured on CPU: "base" runs at ~3.4x realtime,
    # so a 25-minute video takes ~7 minutes. "small" is more accurate and about
    # 3x slower; "tiny" is ~2x faster and noticeably worse.
    WHISPER_MODEL: str = "base"

    # =====================================================
    # EXTERNAL TOOLS
    # =====================================================
    YTDLP_PATH: str = ""   # Leave empty to use system PATH; set to full path if in venv only
    FFMPEG_PATH: str = ""
    NODE_PATH: str = ""

    # =====================================================
    # CACHE SETTINGS
    # =====================================================
    VIDEO_CACHE_ENABLED: bool = True
    VIDEO_CACHE_MAX_SIZE_GB: float = 10.0
    VIDEO_CACHE_MAX_AGE_DAYS: int = 30

    # =====================================================
    # DURATION PROFILES
    # =====================================================
    DEFAULT_DURATION_MINUTES: int = 10
    MIN_DURATION_MINUTES: int = 2   # 2-minute "Quick" demo profile
    MAX_DURATION_MINUTES: int = 20

    # =====================================================
    # HUGGING FACE
    # =====================================================
    # Authenticates model downloads. Anonymous pulls share a per-IP quota and
    # start returning 429 once it is exhausted; an authenticated pull does not.
    HF_TOKEN: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def get_hf_token() -> Optional[str]:
    """
    Hugging Face access token for authenticated model downloads, or None.

    Resolution order:
      1. os.environ["HF_TOKEN"]  — token exported into the shell
      2. Settings.HF_TOKEN       — token read from .env by pydantic-settings

    The second source is not optional: pydantic-settings populates the Settings
    object from .env but does NOT write into os.environ, and nothing under
    backend/ calls load_dotenv(). So os.getenv("HF_TOKEN") alone returns None
    when the server runs under uvicorn, which would silently leave every model
    download anonymous.

    None is the documented "no auth" value for the `token=` parameter in both
    transformers and sentence-transformers, so callers can forward the result
    unconditionally without branching.
    """
    token = os.getenv("HF_TOKEN")
    if not token:
        try:
            token = getattr(get_settings(), "HF_TOKEN", "") or ""
        except Exception:
            token = ""
    return token or None
