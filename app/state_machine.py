# app/state_machine.py
from enum import Enum
from typing import Any


class TicketStatus(str, Enum):
    INGESTED = "INGESTED"          # Row landed from CSV, nothing done yet
    SANITIZED = "SANITIZED"        # Defensive PII pass complete
    PROCESSING = "PROCESSING"      # Classification in flight
    TRIAGED = "TRIAGED"            # Classified with acceptable confidence
    NEEDS_REVIEW = "NEEDS_REVIEW"  # Low confidence, conflict, or fallback path
    AI_FAILED = "AI_FAILED"        # API error/timeout/invalid output, retries exhausted
    APPROVED = "APPROVED"          # Operator approved the ack and routing
    RESOLVED = "RESOLVED"          # Operator marked done (for demo/reporting)


ALLOWED_TRANSITIONS: dict[TicketStatus, set[TicketStatus]] = {
    TicketStatus.INGESTED:     {TicketStatus.SANITIZED},
    TicketStatus.SANITIZED:    {TicketStatus.PROCESSING},
    TicketStatus.PROCESSING:   {TicketStatus.TRIAGED, TicketStatus.NEEDS_REVIEW, TicketStatus.AI_FAILED},
    TicketStatus.AI_FAILED:    {TicketStatus.TRIAGED, TicketStatus.NEEDS_REVIEW},  # Fallback classifier handles it
    TicketStatus.TRIAGED:      {TicketStatus.APPROVED, TicketStatus.NEEDS_REVIEW},
    TicketStatus.NEEDS_REVIEW: {TicketStatus.APPROVED},
    TicketStatus.APPROVED:     {TicketStatus.RESOLVED},
    TicketStatus.RESOLVED:     set(),
}


def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    """Checks whether transitioning from current to target status is permitted."""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    return target in allowed


def transition(ticket: Any, target: TicketStatus) -> None:
    """Transitions a ticket to a new status or raises ValueError if invalid."""
    current_status = ticket.status
    # Ensure current_status is treated as TicketStatus enum
    if isinstance(current_status, str):
        current_status = TicketStatus(current_status)

    if not can_transition(current_status, target):
        raise ValueError(f"Illegal state transition from {current_status} to {target}")

    ticket.status = target
