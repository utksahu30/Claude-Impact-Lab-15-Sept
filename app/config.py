import secrets
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # LLM Settings (Defaulting to Qwen 3.8 Max via DashScope)
    llm_provider: str = "qwen"
    qwen_model: str = "qwen3.8-max"
    dashscope_api_key: Optional[str] = None
    dashscope_fallback_api_key: Optional[str] = "sk-ws-H.DHLXIHL.IJT1.MEQCIHWr0_4t4vyDdMVW4ohiSZtcVyxY5EbTg6ugWS7NvP8_AiBrUpr8IKYax2nahDGlT9e2xzNRdws4bdZTnj_Hs5lFgQ"
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
