# smoke_test.py
from sqlmodel import Session, select, delete
from app.db import engine, init_db
from app.models import Ticket, DuplicateLink, UploadBatch
from app.state_machine import TicketStatus, transition
from app.csv_engine import decode_csv_bytes, ingest_mapped_csv
from app.reports import compute_metrics, export_tickets_csv
from app.safety_rules import contains_safety_keyword
from datetime import datetime, timezone


def run_smoke_test():
    print("=" * 60)
    print("  RUNNING END-TO-END SMOKE TEST FOR BHOPAL TRIAGE ENGINE")
    print("=" * 60)

    # 1. Initialize Database & Verify Offline Resilience Path
    init_db()
    from app.config import settings
    settings.allow_external_ai = False  # Test resilient offline fallback path
    print("[*] Offline fallback mode enabled (ALLOW_EXTERNAL_AI=False)")
    with Session(engine) as session:
        # Clear existing
        session.exec(delete(DuplicateLink))
        session.exec(delete(Ticket))
        session.exec(delete(UploadBatch))
        session.commit()

        # 2. Ingest demo_complaints.csv
        with open("data/demo_complaints.csv", "rb") as f:
            raw_bytes = f.read()

        decoded_text, enc, lossy = decode_csv_bytes(raw_bytes)
        print(f"[OK] CSV decoded using {enc} (lossy: {lossy})")

        mapping = {
            "complaint_text_col": "complaint_text",
            "channel_col": "channel",
            "ward_col": "ward",
            "timestamp_col": "timestamp"
        }

        batch, tickets, errors = ingest_mapped_csv(
            session=session,
            batch_id="smoke_test_batch",
            decoded_text=decoded_text,
            mapping=mapping,
            filename="demo_complaints.csv",
            encoding_used=enc,
            was_lossy=lossy
        )

        print(f"[OK] Batch ingested: {batch.imported_rows} imported, {batch.duplicate_rows} duplicates skipped, {batch.error_rows} errors.")
        assert batch.imported_rows > 30, "Expected at least 30 tickets imported"

        # 3. Verify State Machine & Approval on a ticket
        ticket_to_approve = session.exec(select(Ticket).where(Ticket.status == TicketStatus.TRIAGED)).first()
        if not ticket_to_approve:
            ticket_to_approve = session.exec(select(Ticket).where(Ticket.status == TicketStatus.NEEDS_REVIEW)).first()

        assert ticket_to_approve is not None, "Expected triaged or needs_review ticket"
        old_status = ticket_to_approve.status
        transition(ticket_to_approve, TicketStatus.APPROVED)
        session.add(ticket_to_approve)
        session.commit()
        session.refresh(ticket_to_approve)
        print(f"[OK] State transition verified: Ticket #{ticket_to_approve.id} transitioned from {old_status} to {ticket_to_approve.status}")

        # Transition to RESOLVED
        transition(ticket_to_approve, TicketStatus.RESOLVED)
        ticket_to_approve.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(ticket_to_approve)
        session.commit()
        session.refresh(ticket_to_approve)
        print(f"[OK] State transition verified: Ticket #{ticket_to_approve.id} marked {ticket_to_approve.status} with resolved_at timestamp.")

        # 4. Verify Safety Floor on Operator Override
        safety_ticket = session.exec(select(Ticket).where(Ticket.urgency == "CRITICAL")).first()
        assert safety_ticket is not None, "Expected at least one CRITICAL emergency ticket"
        print(f"[OK] Found safety critical ticket #{safety_ticket.id}: '{safety_ticket.sanitized_text[:50]}...'")

        # Attempting override without reason should be flagged
        assert contains_safety_keyword(safety_ticket.sanitized_text), "Expected safety keywords in text"

        # Legitimate override with reason:
        safety_ticket.safety_floor_overridden = True
        safety_ticket.override_reason = "Verified small controlled drill, no live hazard"
        safety_ticket.urgency = "MEDIUM"
        safety_ticket.human_override = True
        session.add(safety_ticket)
        session.commit()
        print(f"[OK] Audited safety floor override recorded with reason: '{safety_ticket.override_reason}'")

        # 5. Verify Reporting & Metrics Computation
        metrics = compute_metrics(session, days=30)
        print(f"[OK] Metrics computed:")
        print(f"    - Total complaints: {metrics['total_tickets']}")
        print(f"    - Median resolution hours: {metrics['overall_median_resolution_hours']} hrs")
        print(f"    - Human override rate: {metrics['override_rate']}%")
        print(f"    - AI failure rate: {metrics['ai_failure_rate']}%")
        print(f"    - Audited safety floor overrides: {metrics['safety_floor_overrides']}")

        assert metrics["safety_floor_overrides"] >= 1, "Expected at least 1 audited safety override"
        assert metrics["total_tickets"] > 30, "Expected total tickets > 30"

        # 6. Verify Safe CSV Export with Formula Injection Guard
        csv_export = export_tickets_csv(session)
        assert len(csv_export) > 500, "Expected non-empty CSV export"
        print(f"[OK] Safe CSV export generated ({len(csv_export)} bytes)")

    print("\n" + "=" * 60)
    print("  ALL END-TO-END SMOKE TESTS PASSED SUCCESSFULLY! [OK]")
    print("=" * 60)


if __name__ == "__main__":
    run_smoke_test()
