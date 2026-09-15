# app/schemas.py
from pydantic import BaseModel, Field
from typing import Literal, Optional


class ClassificationResult(BaseModel):
    """Strictly validated structured output for triage classification."""
    department: str
    category: str
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning_terms: list[str] = Field(default_factory=list)
    ward: str = Field(default="UNKNOWN")
    urgency: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    ack_draft_en: str = Field(default="Your complaint has been logged and forwarded to the zonal team.")
    ack_draft_hi: Optional[str] = Field(default="आपकी शिकायत दर्ज कर ली गई है और संबंधित जोनल टीम को भेज दी गई है।")


class ColumnMappingRequest(BaseModel):
    """Dynamic column mapping submitted by the operator for arbitrary CSV exports."""
    batch_id: str
    complaint_text_col: str
    channel_col: Optional[str] = None
    timestamp_col: Optional[str] = None
    ward_col: Optional[str] = None


class TicketOverrideRequest(BaseModel):
    """Human-in-the-loop operator override schema with safety floor audit support."""
    department: Optional[str] = None
    category: Optional[str] = None
    ward: Optional[str] = None
    urgency: Optional[Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]] = None
    ack_draft_en: Optional[str] = None
    ack_draft_hi: Optional[str] = None
    override_reason: Optional[str] = None
