# app/main.py
import os
import re
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, Form, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .config import settings
from .db import init_db, get_session
from .models import Ticket, DuplicateLink, UploadBatch
from .state_machine import TicketStatus, transition, can_transition
from .safety_rules import contains_safety_keyword, get_matched_safety_keywords
from .gazetteer import normalize_ward, extract_ward_from_text
from .csv_engine import decode_csv_bytes, inspect_csv_columns, ingest_mapped_csv
from .reports import compute_metrics, export_tickets_csv

app = FastAPI(
    title="Bhopal Civic Triage Engine",
    description="Municipal Complaint Triage and Deduplication System (PS-5)",
    version="1.0.0"
)

# Static and Templates
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Temporary in-memory cache for CSV column mapping step: {temp_file_id: (decoded_text, filename)}
TEMP_UPLOAD_STORE: dict[str, tuple[str, str]] = {}


@app.on_event("startup")
def on_startup():
    init_db()
    print(f"===============================================================")
    print(f" Bhopal Civic Triage Engine (PS-5) Initialized")
    print(f" LLM Provider: {settings.llm_provider.upper()} ({settings.qwen_model})")
    print(f" External AI Allowed: {settings.allow_external_ai}")
    print(f" Demo Auth Token: {settings.demo_token}")
    print(f" Web UI: http://127.0.0.1:8000/tickets")
    print(f"===============================================================")


def get_taxonomy_departments() -> list[str]:
    tax_file = BASE_DIR.parent / "data" / "taxonomy.json"
    if tax_file.exists():
        try:
            with open(tax_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [d["name"] for d in data.get("departments", [])]
        except Exception:
            pass
    return ["Water Supply", "Sanitation", "Electricity", "Roads & Infrastructure", "Drainage & Sewage", "Stray Animals", "Public Health", "Encroachment"]


@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/tickets", status_code=status.HTTP_302_FOUND)


# ---------------------------------------------------------------------------
# Ticket Queue
# ---------------------------------------------------------------------------
@app.get("/tickets", response_class=HTMLResponse)
def ticket_queue(
    request: Request,
    status: Optional[str] = None,
    session: Session = Depends(get_session)
):
    query = select(Ticket).order_by(Ticket.id.desc())
    if status and status in [s.value for s in TicketStatus]:
        query = query.where(Ticket.status == TicketStatus(status))

    tickets = list(session.exec(query).all())

    # Calculate status counts for filter tabs
    all_tickets = session.exec(select(Ticket)).all()
    counts = {
        "total": len(all_tickets),
        "needs_review": sum(1 for t in all_tickets if t.status == TicketStatus.NEEDS_REVIEW),
        "triaged": sum(1 for t in all_tickets if t.status == TicketStatus.TRIAGED),
        "approved": sum(1 for t in all_tickets if t.status == TicketStatus.APPROVED),
        "resolved": sum(1 for t in all_tickets if t.status == TicketStatus.RESOLVED),
    }

    # Find tickets that belong to duplicate clusters
    dup_links = session.exec(select(DuplicateLink)).all()
    dup_ticket_ids = {link.ticket_id for link in dup_links}

    return templates.TemplateResponse(
        request=request,
        name="queue.html",
        context={
            "tickets": tickets,
            "counts": counts,
            "current_status": status,
            "duplicate_ticket_ids": dup_ticket_ids,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "tickets"
        }
    )


# ---------------------------------------------------------------------------
# Ticket Inspector & Human-in-the-Loop Actions
# ---------------------------------------------------------------------------
@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(
    ticket_id: int,
    request: Request,
    alert_msg: Optional[str] = None,
    session: Session = Depends(get_session)
):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # Parse reasoning terms
    reasoning_terms_list = []
    if ticket.reasoning_terms:
        try:
            reasoning_terms_list = json.loads(ticket.reasoning_terms)
        except Exception:
            reasoning_terms_list = [ticket.reasoning_terms]

    # Check emergency safety keywords in complaint
    safety_keywords_detected = get_matched_safety_keywords(ticket.sanitized_text)

    # Highlight reasoning and safety terms inline in the sanitized text
    highlighted_text = ticket.sanitized_text
    # 1. Highlight safety keywords in red
    for kw in safety_keywords_detected:
        pattern = re.compile(re.escape(kw), re.IGNORECASE)
        highlighted_text = pattern.sub(f'<span class="highlight-safety">{kw}</span>', highlighted_text)

    # 2. Highlight reasoning terms in yellow
    for term in reasoning_terms_list:
        if term and term.lower() not in [kw.lower() for kw in safety_keywords_detected] and len(term) > 2:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            highlighted_text = pattern.sub(f'<span class="highlight-term">{term}</span>', highlighted_text)

    # Find linked tickets in the same duplicate cluster
    dup_links = session.exec(select(DuplicateLink).where(DuplicateLink.ticket_id == ticket.id)).all()
    duplicate_tickets: list[Ticket] = []
    if dup_links:
        cluster_id = dup_links[0].duplicate_of_cluster
        other_links = session.exec(select(DuplicateLink).where(DuplicateLink.duplicate_of_cluster == cluster_id)).all()
        other_ids = [l.ticket_id for l in other_links if l.ticket_id != ticket.id]
        if other_ids:
            duplicate_tickets = list(session.exec(select(Ticket).where(Ticket.id.in_(other_ids))).all())

    # PII metadata
    pii_meta = {}
    if ticket.pii_redaction_metadata:
        try:
            pii_meta = json.loads(ticket.pii_redaction_metadata)
        except Exception:
            pass

    return templates.TemplateResponse(
        request=request,
        name="ticket_detail.html",
        context={
            "ticket": ticket,
            "highlighted_text": highlighted_text,
            "reasoning_terms_list": reasoning_terms_list,
            "safety_keywords_detected": safety_keywords_detected,
            "duplicate_tickets": duplicate_tickets,
            "taxonomy_departments": get_taxonomy_departments(),
            "pii_meta": pii_meta,
            "alert_msg": alert_msg,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "tickets"
        }
    )


@app.post("/tickets/{ticket_id}/override", response_class=HTMLResponse)
def ticket_override(
    ticket_id: int,
    request: Request,
    department: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    ward: Optional[str] = Form(None),
    urgency: Optional[str] = Form(None),
    override_reason: Optional[str] = Form(None),
    auto_approve: Optional[bool] = Form(False),
    session: Session = Depends(get_session)
):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    new_urgency = urgency or ticket.urgency

    # Enforce Precedence Rule on Operator Overrides:
    # If text has safety keywords and operator tries to lower urgency from CRITICAL to MEDIUM/LOW,
    # an audited reason is MANDATORY.
    if contains_safety_keyword(ticket.sanitized_text) and new_urgency in ("MEDIUM", "LOW") and ticket.urgency == "CRITICAL":
        if not override_reason or not override_reason.strip():
            return ticket_detail(
                ticket_id=ticket_id,
                request=request,
                alert_msg="Precedence Violation: A written justification reason is required to lower urgency on a safety-flagged ticket.",
                session=session
            )
        ticket.safety_floor_overridden = True
        ticket.override_reason = override_reason.strip()

    # Track if any routing categorization actually changed
    has_changed = False
    if department and department != ticket.department:
        ticket.department = department
        has_changed = True
    if category and category != ticket.category:
        ticket.category = category
        has_changed = True
    if ward:
        norm_w = normalize_ward(ward) or ward
        if norm_w != ticket.ward:
            ticket.ward = norm_w
            has_changed = True
    if new_urgency and new_urgency != ticket.urgency:
        ticket.urgency = new_urgency
        has_changed = True

    if has_changed:
        ticket.human_override = True

    # If auto_approve requested or operator clicked 'Approve & Lock'
    if auto_approve and can_transition(ticket.status, TicketStatus.APPROVED):
        transition(ticket, TicketStatus.APPROVED)

    session.add(ticket)
    session.commit()

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/tickets/{ticket_id}/approve", response_class=RedirectResponse)
def ticket_approve(
    ticket_id: int,
    department: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    ward: Optional[str] = Form(None),
    urgency: Optional[str] = Form(None),
    override_reason: Optional[str] = Form(None),
    ack_draft_en: Optional[str] = Form(None),
    ack_draft_hi: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # If operator changed categorization fields while approving
    has_changed = False
    if department and department != ticket.department:
        ticket.department = department
        has_changed = True
    if category and category != ticket.category:
        ticket.category = category
        has_changed = True
    if ward:
        norm_w = normalize_ward(ward) or ward
        if norm_w != ticket.ward:
            ticket.ward = norm_w
            has_changed = True
    if urgency and urgency != ticket.urgency:
        if contains_safety_keyword(ticket.sanitized_text) and urgency in ("MEDIUM", "LOW") and ticket.urgency == "CRITICAL":
            if override_reason and override_reason.strip():
                ticket.safety_floor_overridden = True
                ticket.override_reason = override_reason.strip()
        ticket.urgency = urgency
        has_changed = True

    if has_changed:
        ticket.human_override = True

    # Validate state transition guard (Section 4)
    if can_transition(ticket.status, TicketStatus.APPROVED):
        transition(ticket, TicketStatus.APPROVED)

    if ack_draft_en:
        ticket.ack_draft_en = ack_draft_en
    if ack_draft_hi:
        ticket.ack_draft_hi = ack_draft_hi

    session.add(ticket)
    session.commit()

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/tickets/{ticket_id}/resolve", response_class=RedirectResponse)
def ticket_resolve(
    ticket_id: int,
    session: Session = Depends(get_session)
):
    ticket = session.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    # State machine transition guard
    transition(ticket, TicketStatus.RESOLVED)
    ticket.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)

    session.add(ticket)
    session.commit()

    return RedirectResponse(url=f"/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# CSV Ingestion & Dynamic Column Mapping
# ---------------------------------------------------------------------------
@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "mapping_step": False,
            "success_batch": None,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "upload"
        }
    )


@app.post("/upload", response_class=HTMLResponse)
async def handle_csv_upload(
    request: Request,
    file: UploadFile = File(...)
):
    # Size check
    contents = await file.read()
    if len(contents) > settings.max_upload_mb * 1024 * 1024:
        return templates.TemplateResponse(
            request=request,
            name="upload.html",
            context={
                "error_msg": f"File size exceeds limit of {settings.max_upload_mb} MB.",
                "mapping_step": False,
                "demo_token": settings.demo_token,
                "allow_external_ai": settings.allow_external_ai,
                "active_page": "upload"
            }
        )

    # Real Charset Detection (Section 8)
    decoded_text, encoding_used, was_lossy = decode_csv_bytes(contents)

    try:
        headers, sample_rows, total_rows = inspect_csv_columns(decoded_text)
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="upload.html",
            context={
                "error_msg": f"Invalid CSV file: {str(e)}",
                "mapping_step": False,
                "demo_token": settings.demo_token,
                "allow_external_ai": settings.allow_external_ai,
                "active_page": "upload"
            }
        )

    temp_id = str(uuid.uuid4())
    TEMP_UPLOAD_STORE[temp_id] = (decoded_text, file.filename or "upload.csv")

    batch_id = f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "mapping_step": True,
            "temp_file_id": temp_id,
            "batch_id": batch_id,
            "filename": file.filename,
            "headers": headers,
            "sample_rows": sample_rows,
            "encoding_detected": encoding_used,
            "was_lossy": was_lossy,
            "total_rows": total_rows,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "upload"
        }
    )


@app.post("/upload/confirm", response_class=HTMLResponse)
def confirm_csv_mapping(
    request: Request,
    temp_file_id: str = Form(...),
    batch_id: str = Form(...),
    filename: str = Form(...),
    encoding_used: str = Form(...),
    was_lossy: str = Form(...),
    complaint_text_col: str = Form(...),
    channel_col: Optional[str] = Form(None),
    ward_col: Optional[str] = Form(None),
    timestamp_col: Optional[str] = Form(None),
    session: Session = Depends(get_session)
):
    if temp_file_id not in TEMP_UPLOAD_STORE:
        raise HTTPException(status_code=400, detail="Uploaded file session expired. Please re-upload.")

    decoded_text, _ = TEMP_UPLOAD_STORE.pop(temp_file_id)

    mapping = {
        "complaint_text_col": complaint_text_col,
        "channel_col": channel_col if channel_col else None,
        "ward_col": ward_col if ward_col else None,
        "timestamp_col": timestamp_col if timestamp_col else None
    }

    batch, _, errors = ingest_mapped_csv(
        session=session,
        batch_id=batch_id,
        decoded_text=decoded_text,
        mapping=mapping,
        filename=filename,
        encoding_used=encoding_used,
        was_lossy=(was_lossy.lower() == "true")
    )

    return templates.TemplateResponse(
        request=request,
        name="upload.html",
        context={
            "mapping_step": False,
            "success_batch": batch,
            "batch_errors": errors,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "upload"
        }
    )


# ---------------------------------------------------------------------------
# Weekly Digest & Reporting
# ---------------------------------------------------------------------------
@app.get("/digest", response_class=HTMLResponse)
def weekly_digest(
    request: Request,
    days: int = 30,
    session: Session = Depends(get_session)
):
    metrics = compute_metrics(session, days=days)
    return templates.TemplateResponse(
        request=request,
        name="digest.html",
        context={
            "metrics": metrics,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "digest"
        }
    )


@app.get("/digest/export.csv")
def export_csv_report(session: Session = Depends(get_session)):
    csv_content = export_tickets_csv(session)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bhopal_civic_tickets.csv"}
    )


# ---------------------------------------------------------------------------
# Held-Out Evaluation Benchmark
# ---------------------------------------------------------------------------
@app.get("/eval", response_class=HTMLResponse)
def evaluation_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="eval_dashboard.html",
        context={
            "eval_results": None,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "eval"
        }
    )


@app.post("/eval/run", response_class=HTMLResponse)
def run_evaluation_benchmark(request: Request):
    from .evaluation import run_held_out_benchmark
    eval_results = run_held_out_benchmark()
    return templates.TemplateResponse(
        request=request,
        name="eval_dashboard.html",
        context={
            "eval_results": eval_results,
            "demo_token": settings.demo_token,
            "allow_external_ai": settings.allow_external_ai,
            "active_page": "eval"
        }
    )


# ---------------------------------------------------------------------------
# Demo Reseed Endpoint
# ---------------------------------------------------------------------------
@app.get("/admin/reset", response_class=RedirectResponse)
def reset_demo_data(session: Session = Depends(get_session)):
    from sqlmodel import delete
    try:
        session.exec(delete(DuplicateLink))
        session.exec(delete(Ticket))
        session.exec(delete(UploadBatch))
        session.commit()

        # Search for demo_complaints.csv across possible deployment directory layouts
        candidate_paths = [
            BASE_DIR.parent / "data" / "demo_complaints.csv",
            BASE_DIR / "data" / "demo_complaints.csv",
            Path("data") / "demo_complaints.csv",
            Path("/app/data") / "demo_complaints.csv"
        ]
        demo_csv = next((p for p in candidate_paths if p.exists()), None)
        if demo_csv:
            with open(demo_csv, "rb") as f:
                raw_bytes = f.read()
            decoded_text, enc, lossy = decode_csv_bytes(raw_bytes)
            mapping = {
                "complaint_text_col": "complaint_text",
                "channel_col": "channel",
                "ward_col": "ward",
                "timestamp_col": "timestamp"
            }
            ingest_mapped_csv(
                session=session,
                batch_id="demo_initial_seed",
                decoded_text=decoded_text,
                mapping=mapping,
                filename="demo_complaints.csv",
                encoding_used=enc,
                was_lossy=lossy
            )
    except Exception as e:
        print(f"[admin/reset] Warning encountered during data reset: {e}", flush=True)

    return RedirectResponse(url="/tickets", status_code=status.HTTP_302_FOUND)
