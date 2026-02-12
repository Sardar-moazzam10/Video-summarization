"""
Core configuration - Single source of truth
Production-ready settings with security
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache
from typing import List
import secrets


class Settings(BaseSettings):
    # =====================================================
    # APP SETTINGS
    # =====================================================
    APP_NAME: str = "AI Video Summarizer"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # =====================================================
    # SECURITY (CRITICAL)
    # =====================================================
    SECRET_KEY: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        description="JWT signing key - MUST set in production"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    RATE_LIMIT_BURST: int = 10

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
    MAIL_USE_TLS: bool = True
    MAIL_USERNAME: str = ""
    MAIL_PASSWORD: str = ""

    # =====================================================
    # EXTERNAL APIs
    # =====================================================
    ELEVEN_API_KEY: str = ""
    YOUTUBE_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    GEMINI_FALLBACK_TO_BART: bool = True

    # =====================================================
    # AI/ML SETTINGS
    # =====================================================
    SUMMARIZATION_MODEL: str = "facebook/bart-large-cnn"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    WHISPER_MODEL: str = "base"

    # =====================================================
    # CACHE SETTINGS
    # =====================================================
    VIDEO_CACHE_ENABLED: bool = True
    VIDEO_CACHE_MAX_SIZE_GB: float = 10.0
    VIDEO_CACHE_MAX_AGE_DAYS: int = 30
    TRANSCRIPT_CACHE_ENABLED: bool = True
    AUDIO_CACHE_ENABLED: bool = True

    # =====================================================
    # DURATION PROFILES
    # =====================================================
    DEFAULT_DURATION_MINUTES: int = 10
    MIN_DURATION_MINUTES: int = 5
    MAX_DURATION_MINUTES: int = 20

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
