# app/models.py
from datetime import datetime, timezone
from typing import Optional
from sqlmodel import SQLModel, Field
from .state_machine import TicketStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True)                  # Traces ticket back to its CSV batch
    ticket_hash: str = Field(index=True, unique=True)  # SHA-256 idempotency key
    source_channel: str = Field(default="Helpline")    # Helpline, WhatsApp, CM Helpline, Mobile App, etc.
    raw_text: str = Field(default="")                  # Stored only if ALLOW_RAW_TEXT_RETENTION=True
    sanitized_text: str = Field(index=False)           # Defensive PII sanitized text
    pii_redaction_metadata: Optional[str] = None       # JSON string of redacted counts/types only

    department: Optional[str] = Field(default=None, index=True)
    category: Optional[str] = None
    urgency: str = Field(default="MEDIUM", index=True) # CRITICAL, HIGH, MEDIUM, LOW
    ward: Optional[str] = Field(default=None, index=True)
    confidence: float = 0.0
    reasoning_terms: Optional[str] = None              # JSON array of keywords
    ack_draft_en: Optional[str] = None                 # English acknowledgement draft
    ack_draft_hi: Optional[str] = None                 # Hindi acknowledgement draft
    classification_method: Optional[str] = None        # "llm" | "fallback_rules" | "safety_override"
    prompt_version: Optional[str] = None

    status: TicketStatus = Field(default=TicketStatus.INGESTED, index=True)
    human_override: bool = False
    created_at: datetime = Field(default_factory=utc_now, index=True)
    resolved_at: Optional[datetime] = None

    # Durable audit flags (survive status transitions for accurate reporting)
    ai_failed: bool = Field(default=False, index=True)
    ai_failure_reason: Optional[str] = None
    safety_floor_overridden: bool = Field(default=False, index=True)
    override_reason: Optional[str] = None


class DuplicateLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(index=True)
    duplicate_of_cluster: str = Field(index=True)      # Connected component cluster identifier
    similarity_score: float = 0.0
    method: str = Field(default="tfidf_char_ngram")
    confirmed_by_operator: bool = False


class UploadBatch(SQLModel, table=True):
    id: str = Field(primary_key=True)                  # UUID or batch string
    filename: str
    total_rows: int = 0
    imported_rows: int = 0
    duplicate_rows: int = 0
    error_rows: int = 0
    encoding_detected: str = "utf-8"
    was_lossy: bool = False
    column_mapping_json: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
