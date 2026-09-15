import secrets
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # LLM Provider & Model Settings
    # Supports "gemini" (Google AI Studio) and "qwen" (Alibaba DashScope)
    llm_provider: str = "gemini"
    
    # Gemini Settings (Google AI Studio)
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.6-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    # Qwen / DashScope Settings (Backup / Alternative)
    qwen_model: str = "qwen3.8-max"
    dashscope_api_key: Optional[str] = None
    dashscope_fallback_api_key: Optional[str] = None
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    
    # Anthropic compatibility option
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_api_key: Optional[str] = None

    # Thresholds and operational controls
    ai_timeout_seconds: float = 45.0
    ai_max_retries: int = 3
    confidence_review_threshold: float = 0.6
    duplicate_similarity_threshold: float = 0.82  # Single source of truth for dedup similarity
    allow_external_ai: bool = True               # Flip to False for offline-resilience demo
    allow_raw_text_retention: bool = False       # PII posture: retain sanitized_text only by default
    demo_token: Optional[str] = None             # Randomly generated at startup if not provided in .env
    max_upload_mb: int = 10
    max_rows_per_batch: int = 2000
    database_url: str = "sqlite:///bhopal_triage.db"


settings = Settings()

# Dynamic token generation to prevent hardcoded secrets
if not settings.demo_token:
    settings.demo_token = secrets.token_urlsafe(16)
    print(f"[startup] No DEMO_TOKEN set in .env — generated one for this session: {settings.demo_token}")
