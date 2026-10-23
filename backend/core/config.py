"""
Core configuration - Single source of truth
Production-ready settings with security
"""
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from functools import lru_cache
from typing import List, Optional
import os
import secrets


class Settings(BaseSettings):
    # =====================================================
    # APP SETTINGS
    # =====================================================
    APP_NAME: str = "VidFusion"
    ENVIRONMENT: str = "development"

    # =====================================================
    # SECURITY (CRITICAL)
    # =====================================================
    SECRET_KEY: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description="JWT signing key - MUST set in production"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 720  # 30 days

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000"
    ]

    # =====================================================
    # DATABASE & CACHE
    # =====================================================
    MONGODB_URI: str = "mongodb://localhost:27017/"
    MONGODB_DATABASE: str = "video-summarizer"

    # Redis Queue (ARQ background job worker)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_QUEUE_ENABLED: bool = True

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

    # =====================================================
    # AI/ML SETTINGS
    # =====================================================
    SUMMARIZATION_MODEL: str = "sshleifer/distilbart-cnn-12-6"  # 306 MB vs 1.6 GB BART-large, 95% quality
    EMBEDDING_MODEL: str = "BAAI/bge-base-en-v1.5"              # #1 MTEB 2024, 768-dim, replaces all-MiniLM
    CLIP_MODEL: str = "openai/clip-vit-base-patch16"            # ViT-B/16: 17% better than B/32, same API

    # When enabled, the API/core worker stops at evidence-manifest publication
    # and durable video/text workers consume that immutable handoff. Disabled
    # by default for direct local runs that have not started worker processes.
    SEPARATE_OUTPUT_WORKERS_ENABLED: bool = False

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
    # Kept under the existing name for compatibility with current .env files.
    # YouTube search is performed server-side so this key is never sent to browsers.
    REACT_APP_YOUTUBE_API_KEY: str = ""

    # =====================================================
    # CACHE & STORAGE HYGIENE SETTINGS
    # =====================================================
    VIDEO_CACHE_ENABLED: bool = True
    VIDEO_CACHE_MAX_SIZE_GB: float = 10.0
    VIDEO_CACHE_MAX_AGE_DAYS: int = 30
    HIGHLIGHTS_MAX_SIZE_GB: float = 10.0
    HIGHLIGHTS_MAX_AGE_DAYS: int = 14
    TEMP_SCRATCH_MAX_AGE_MINUTES: int = 30

    # =====================================================
    # TRANSLATION (non-English caption fast path)
    # =====================================================
    # deep-translator's GoogleTranslator issues a plain requests.get() with no
    # timeout param, so a stalled/blocked connection would otherwise hang the
    # calling thread forever. This bounds a single request.
    TRANSLATION_REQUEST_TIMEOUT_SECONDS: float = 8.0
    # Hard ceiling on the whole batched Google-translate pass for one video's
    # transcript, regardless of how many chunks fail. Once hit, any remaining
    # segments are left untranslated rather than retried further.
    TRANSLATION_STAGE_TIMEOUT_SECONDS: float = 60.0
    # Outer bound around translating one transcript (Google fast path, run via
    # asyncio.to_thread so it can't block the event loop / progress SSE
    # stream). Comfortably above TRANSLATION_STAGE_TIMEOUT_SECONDS to leave
    # room for the language-detect + per-segment work around it.
    TRANSCRIPT_TRANSLATION_TIMEOUT_SECONDS: float = 90.0
    # Consecutive whole-chunk Google failures before giving up on it entirely
    # for this transcript, instead of grinding through the full
    # TRANSLATION_STAGE_TIMEOUT_SECONDS budget one doomed chunk at a time.
    # Measured on a real rate-limited run (Nkaa8fPEtQk, 1467 segments): once
    # Google starts blocking, every subsequent chunk fails identically.
    TRANSLATION_CIRCUIT_BREAKER_FAILURES: int = 3
    # NLLB-200 on CPU measured ~2.3s/segment even batched (benchmark: a
    # 32-segment batch with max_new_tokens=64 took 74.9s on the real
    # Nkaa8fPEtQk transcript). Fine for a short clip; for a 1467-segment/
    # 51-minute video that projects to ~57 minutes — unusable interactively.
    # Only attempt the segment-preserving NLLB fallback when the transcript
    # is short enough to plausibly finish within TRANSLATION_STAGE_TIMEOUT_
    # SECONDS; longer transcripts skip it entirely rather than burning over a
    # minute before giving up anyway.
    NLLB_MAX_SEGMENTS_FOR_FALLBACK: int = 30
    # Long multilingual sources are translated by Whisper in bounded on-disk chunks.
    TRANSCRIPT_SOURCE_TIMEOUT_SECONDS: float = Field(default=900.0, gt=0)
    WHISPER_CPU_THREADS: int = Field(default=4, ge=1, le=32)
    WHISPER_CHUNK_SECONDS: float = 60.0
    WHISPER_CHUNK_OVERLAP_SECONDS: float = 1.0
    WHISPER_AUDIO_DOWNLOAD_TIMEOUT_SECONDS: float = 180.0
    # Maximum audio duration (seconds) eligible for CPU Whisper speech-to-text.
    # Videos longer than 20 minutes (1200s) on CPU exceed the 15-minute deadline;
    # skipping Whisper prevents hanging CPU cores for 15 minutes before an abort.
    MAX_WHISPER_AUDIO_DURATION_SECONDS: float = Field(default=1200.0, gt=0)

    # =====================================================
    # DURATION PROFILES
    # =====================================================
    DEFAULT_DURATION_MINUTES: int = 10
    MIN_DURATION_MINUTES: int = 5
    # 30 = "Comprehensive Summary". One duration-aware optimizer serves every
    # mode (see coverage_selector.select_segments) — only the budget changes.
    MAX_DURATION_MINUTES: int = 30

    # =====================================================
    # SEMANTIC SEGMENT SELECTION
    # =====================================================
    # Master switch for the coverage-aware pipeline: semantic segmentation ->
    # concept extraction -> submodular budgeted selection. Set false to fall
    # back to the legacy top-score clip selection in segment_extractor.py.
    ENABLE_SEMANTIC_SELECTION: bool = True

    # Use Ollama for concept extraction.
    #
    # Off by default for the same measured performance reason:
    # llama3.2:3b on CPU cannot finish this stage in a usable time.
    #
    # Benchmarked here, one chunk per row:
    #     450 words,  799 prompt tokens,  99 generated  -> 179.7 s
    #     700 words, 1107 prompt tokens, 175 generated  -> 183.9 s
    # Roughly 180 s per chunk, and the split shows why: the time is prompt
    # evaluation, not generation, so capping num_predict does not help. A repeat
    # of the first row came back in 66.8 s, but only because an identical prefix
    # was still in Ollama's KV cache — in a real run every chunk is different
    # text, so that number does not apply.
    #
    # A 25-minute video is 14 sampled chunks; at two in flight that is roughly
    # 21 minutes of concept extraction before the stage times out and falls back
    # anyway.
    #
    # The fallback is not a stub. TF-IDF keyphrases with a spoken-filler stop
    # list pull real domain vocabulary out of a real podcast — on an 82-minute
    # sleep episode: light, sleep, melatonin, sunlight, cortisol, adenosine,
    # caffeine. Weaker than the LLM's named-and-explained concepts, but honest,
    # instant and deterministic.
    #
    # Set ENABLE_CONCEPT_LLM=true on a GPU machine, or with a smaller/faster
    # model, to get the better concepts. The code path is complete and tested;
    # only the default reflects this hardware.
    ENABLE_CONCEPT_LLM: bool = False

    # Wall-clock caps for the concept stage. Per-chunk keeps one slow generation
    # from stalling the batch; total bounds the whole stage so a long podcast
    # cannot push the job past a usable runtime.
    CONCEPT_CHUNK_TIMEOUT_SECONDS: float = 45.0
    CONCEPT_TOTAL_TIMEOUT_SECONDS: float = 300.0
    CONCEPT_TOP_K: int = 25

    # Semantic segment bounds, in seconds. A segment is the unit the optimizer
    # picks and ffmpeg cuts, so these set how long a single "complete thought"
    # clip may run. Below ~15s a clip reads as channel-surfing; above ~120s a
    # single segment can swallow a short budget on its own.
    SEGMENT_MIN_SECONDS: float = 20.0
    SEGMENT_MAX_SECONDS: float = 90.0

    # =====================================================
    # SELECTION SCORING WEIGHTS
    # =====================================================
    # score = CONCEPT * concept_coverage_gain     (submodular: diminishing)
    #       + SEMANTIC * relevance                (how on-topic the segment is)
    #       + COVERAGE * temporal_coverage_gain   (concave: rewards new regions)
    #       + COHERENCE * completeness            (clean start/end boundaries)
    #       - REDUNDANCY * similarity_to_selected (penalty)
    #       - DURATION_PENALTY * relative_length  (mild bias to shorter picks)
    #
    # Concept + coverage together (0.60) outweigh raw relevance (0.20):
    # relevance alone is what produced the beginning-heavy selections, because
    # early segments introduce the topic and therefore look most similar to any
    # summary of it.
    #
    # The 0.28/0.32 split between coverage and concept is measured, not assumed.
    # Against a hand-authored gold standard of 103 important concepts over 7
    # videos in 5 genres (see evaluation/), and scored with the same BART
    # summary reference the merge pipeline supplies at runtime, coverage 0.28
    # raised F1 from 0.637 to 0.662 over the previous 0.25.
    #
    # 0.35 reaches the same F1 but is not used: it trips the shipped-config
    # diversity guard in tests/test_coverage_selector.py, selecting 7 of 10
    # near-identical segments where 0.28 selects 2, because past ~0.32 a fresh
    # temporal bin outbids the redundancy penalty when no concept signal is
    # available. 0.28 is also better on the 5-minute mode (0.546 vs 0.532).
    #
    # An earlier sweep that scored selections WITHOUT the summary reference
    # favoured 0.35 much more strongly; that measurement did not reflect
    # production, which always has one. Tune per content type via .env.
    SELECT_CONCEPT_WEIGHT: float = 0.32
    SELECT_SEMANTIC_WEIGHT: float = 0.20
    SELECT_COVERAGE_WEIGHT: float = 0.28
    SELECT_COHERENCE_WEIGHT: float = 0.10
    SELECT_REDUNDANCY_PENALTY: float = 0.25
    SELECT_DURATION_PENALTY: float = 0.05

    # The optimizer is allowed to stop before the budget is full only once the
    # reel has reached this fraction of the requested duration — the "duration
    # is approximately respected" tolerance. Lower it to let the optimizer be
    # stricter about quality at the cost of a shorter reel.
    SELECT_MIN_BUDGET_FILL: float = 0.90

    # =====================================================
    # HUGGING FACE
    # =====================================================
    # Authenticates model downloads. Anonymous pulls share a per-IP quota and
    # start returning 429 once it is exhausted; an authenticated pull does not.
    HF_TOKEN: str = ""

    # =====================================================
    # RIGHTS & PUBLICATION
    # =====================================================
    # Rights enforcement mode for publication gating: "warn" or "block"
    RIGHTS_ENFORCEMENT_MODE: str = "warn"

    @model_validator(mode="after")
    def validate_production_security(self):
        """Fail startup instead of silently using an ephemeral/weak key."""
        environment = self.ENVIRONMENT.strip().lower()
        if environment not in {"development", "test", "production"}:
            raise ValueError("ENVIRONMENT must be development, test, or production")
        if self.JWT_ALGORITHM != "HS256":
            raise ValueError("JWT_ALGORITHM must be HS256")
        weak_values = {
            "your-secret-key-here",
            "replace-with-a-random-secret-of-at-least-32-characters",
            "changeme",
            "change-me",
            "secret",
        }
        if environment == "production" and (
            "SECRET_KEY" not in self.model_fields_set
            or len(self.SECRET_KEY) < 32
            or self.SECRET_KEY.lower() in weak_values
        ):
            raise ValueError(
                "Production requires an explicit, unpredictable SECRET_KEY of at least 32 characters"
            )
        return self

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
