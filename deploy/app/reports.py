# app/reports.py
import io
import csv
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from sqlmodel import Session, select, func
from .models import Ticket, DuplicateLink
from .state_machine import TicketStatus


def compute_metrics(session: Session, days: int = 30) -> dict[str, Any]:
    """
    Computes precise municipal KPIs conforming to Section 9 of the PS-5 plan:
    - Resolution time computed ONLY over tickets in RESOLVED status
    - Durable AI failure rate (querying ai_failed flag, not current status)
    - Human override rate and safety-floor override rate reported separately
    - Department-wise breakdown with median resolution hours
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since_date = now - timedelta(days=days)

    # 1. Total processed tickets in window
    statement = select(Ticket).where(Ticket.created_at >= since_date)
    tickets = list(session.exec(statement).all())
    total_tickets = len(tickets)

    if total_tickets == 0:
        return {
            "total_tickets": 0,
            "status_counts": {},
            "urgency_counts": {},
            "ai_failure_rate": 0.0,
            "ai_failed_count": 0,
            "override_rate": 0.0,
            "human_override_count": 0,
            "safety_floor_overrides": 0,
            "safety_floor_audit_list": [],
            "overall_median_resolution_hours": 0.0,
            "department_breakdown": {}
        }

    # 2. Status and urgency distributions
    status_counts: dict[str, int] = {}
    urgency_counts: dict[str, int] = {}
    ai_failed_count = 0
    override_count = 0
    safety_overrides_list = []

    for t in tickets:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1
        urgency_counts[t.urgency] = urgency_counts.get(t.urgency, 0) + 1

        # Durable flag checks
        if t.ai_failed:
            ai_failed_count += 1
        if t.human_override:
            override_count += 1
        if t.safety_floor_overridden:
            safety_overrides_list.append({
                "id": t.id,
                "urgency": t.urgency,
                "reason": t.override_reason or "Unspecified",
                "ward": t.ward or "UNKNOWN",
                "created_at": t.created_at.strftime("%Y-%m-%d %H:%M")
            })

    # AI failure rate = tickets with ai_failed=True / total processed
    ai_failure_rate = round((ai_failed_count / total_tickets) * 100, 1)

    # Triaged / reviewed tickets denominator for override rate
    triaged_tickets = [t for t in tickets if t.status in (TicketStatus.TRIAGED, TicketStatus.APPROVED, TicketStatus.RESOLVED, TicketStatus.NEEDS_REVIEW)]
    override_rate = round((override_count / len(triaged_tickets)) * 100, 1) if triaged_tickets else 0.0

    # 3. Resolution time (computed strictly on tickets in RESOLVED status)
    resolved_tickets = [t for t in tickets if t.status == TicketStatus.RESOLVED and t.resolved_at is not None]
    overall_resolution_hours: list[float] = []

    dept_resolved: dict[str, list[float]] = {}
    dept_totals: dict[str, int] = {}
    dept_urgencies: dict[str, dict[str, int]] = {}

    for t in tickets:
        dept = t.department or "UNASSIGNED"
        dept_totals[dept] = dept_totals.get(dept, 0) + 1
        dept_urgencies.setdefault(dept, {})[t.urgency] = dept_urgencies.setdefault(dept, {}).get(t.urgency, 0) + 1

    for t in resolved_tickets:
        if t.resolved_at:
            hrs = max(0.1, (t.resolved_at - t.created_at).total_seconds() / 3600.0)
            overall_resolution_hours.append(hrs)
            dept = t.department or "UNASSIGNED"
            dept_resolved.setdefault(dept, []).append(hrs)

    overall_median = round(statistics.median(overall_resolution_hours), 1) if overall_resolution_hours else 0.0

    # Per-department metrics
    department_breakdown: dict[str, dict[str, Any]] = {}
    for dept, count in dept_totals.items():
        res_list = dept_resolved.get(dept, [])
        med_hrs = round(statistics.median(res_list), 1) if res_list else None
        department_breakdown[dept] = {
            "total_tickets": count,
            "resolved_count": len(res_list),
            "median_resolution_hours": med_hrs,
            "urgency_counts": dept_urgencies.get(dept, {})
        }

    return {
        "total_tickets": total_tickets,
        "status_counts": status_counts,
        "urgency_counts": urgency_counts,
        "ai_failure_rate": ai_failure_rate,
        "ai_failed_count": ai_failed_count,
        "override_rate": override_rate,
        "human_override_count": override_count,
        "safety_floor_overrides": len(safety_overrides_list),
        "safety_floor_audit_list": safety_overrides_list,
        "overall_median_resolution_hours": overall_median,
        "department_breakdown": department_breakdown
    }


def sanitize_formula_injection(value: Any) -> str:
    """
    Guards against CSV formula injection (Section 9):
    Prefixes any cell starting with =, +, -, or @ with a single quote.
    """
    if value is None:
        return ""
    s = str(value).strip()
    if s and s[0] in ("=", "+", "-", "@"):
        return f"'{s}"
    return s


def export_tickets_csv(session: Session) -> str:
    """Exports all tickets to CSV format with formula injection protection."""
    tickets = session.exec(select(Ticket).order_by(Ticket.id)).all()
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Ticket ID", "Batch ID", "Status", "Channel", "Department", "Category",
        "Ward", "Urgency", "Confidence", "Classification Method", "Human Override",
        "AI Failed", "Safety Overridden", "Created At", "Resolved At", "Sanitized Text"
    ])

    for t in tickets:
        writer.writerow([
            sanitize_formula_injection(t.id),
            sanitize_formula_injection(t.batch_id),
            sanitize_formula_injection(t.status),
            sanitize_formula_injection(t.source_channel),
            sanitize_formula_injection(t.department),
            sanitize_formula_injection(t.category),
            sanitize_formula_injection(t.ward),
            sanitize_formula_injection(t.urgency),
            sanitize_formula_injection(round(t.confidence, 2)),
            sanitize_formula_injection(t.classification_method),
            sanitize_formula_injection(t.human_override),
            sanitize_formula_injection(t.ai_failed),
            sanitize_formula_injection(t.safety_floor_overridden),
            sanitize_formula_injection(t.created_at.strftime("%Y-%m-%d %H:%M:%S")),
            sanitize_formula_injection(t.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if t.resolved_at else ""),
            sanitize_formula_injection(t.sanitized_text)
        ])

    return output.getvalue()
