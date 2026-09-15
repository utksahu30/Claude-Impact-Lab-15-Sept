# tests/test_state_machine.py
import pytest
from app.state_machine import TicketStatus, transition, can_transition


class MockTicket:
    def __init__(self, status=TicketStatus.INGESTED):
        self.status = status


def test_legal_happy_path_transitions():
    ticket = MockTicket(TicketStatus.INGESTED)
    
    transition(ticket, TicketStatus.SANITIZED)
    assert ticket.status == TicketStatus.SANITIZED

    transition(ticket, TicketStatus.PROCESSING)
    assert ticket.status == TicketStatus.PROCESSING

    transition(ticket, TicketStatus.TRIAGED)
    assert ticket.status == TicketStatus.TRIAGED

    transition(ticket, TicketStatus.APPROVED)
    assert ticket.status == TicketStatus.APPROVED

    transition(ticket, TicketStatus.RESOLVED)
    assert ticket.status == TicketStatus.RESOLVED


def test_ai_failed_to_fallback_transition():
    ticket = MockTicket(TicketStatus.PROCESSING)
    
    # AI classification fails -> routes through AI_FAILED
    transition(ticket, TicketStatus.AI_FAILED)
    assert ticket.status == TicketStatus.AI_FAILED

    # Fallback classifier handles it -> moves to NEEDS_REVIEW
    transition(ticket, TicketStatus.NEEDS_REVIEW)
    assert ticket.status == TicketStatus.NEEDS_REVIEW

    # Operator approves reviewed ticket
    transition(ticket, TicketStatus.APPROVED)
    assert ticket.status == TicketStatus.APPROVED


def test_illegal_transitions_raise_value_error():
    # Cannot jump straight from INGESTED to APPROVED
    t1 = MockTicket(TicketStatus.INGESTED)
    with pytest.raises(ValueError):
        transition(t1, TicketStatus.APPROVED)

    # Cannot jump from PROCESSING to APPROVED without triage
    t2 = MockTicket(TicketStatus.PROCESSING)
    with pytest.raises(ValueError):
        transition(t2, TicketStatus.APPROVED)

    # Cannot transition out of RESOLVED (terminal state)
    t3 = MockTicket(TicketStatus.RESOLVED)
    with pytest.raises(ValueError):
        transition(t3, TicketStatus.INGESTED)


def test_can_transition_predicate():
    assert can_transition(TicketStatus.INGESTED, TicketStatus.SANITIZED) is True
    assert can_transition(TicketStatus.INGESTED, TicketStatus.TRIAGED) is False
    assert can_transition(TicketStatus.TRIAGED, TicketStatus.APPROVED) is True
    assert can_transition(TicketStatus.RESOLVED, TicketStatus.APPROVED) is False
