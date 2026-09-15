# app/csv_engine.py
import csv
import io
import hashlib
from datetime import datetime, timezone
from typing import Any, Optional
from charset_normalizer import from_bytes
from sqlmodel import Session

from .config import settings
from .models import Ticket, UploadBatch
from .pii import redact
from .dedup import normalize_text, find_duplicate_clusters
from .ai_classifier import process_ticket


def decode_csv_bytes(raw: bytes) -> tuple[str, str, bool]:
    """
    Decodes raw CSV bytes using real charset detection.
    Prevents silent corruption of Hindi/Devanagari text on Windows-1252 Excel exports.
    Returns:
        (decoded_string, encoding_used, was_lossy)
    """
    # 1. Check UTF-8 / UTF-8-sig first
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding), encoding, False
        except UnicodeDecodeError:
            continue

    # 2. Use charset-normalizer for auto-detection
    detected = from_bytes(raw).best()
    if detected is not None and detected.encoding:
        try:
            return str(detected), detected.encoding, False
        except Exception:
            pass

    # 3. Fallback to lossy replacement as last resort with visible flag
    return raw.decode("utf-8", errors="replace"), "utf-8 (lossy fallback)", True


def inspect_csv_columns(decoded_text: str) -> tuple[list[str], list[dict[str, str]], int]:
    """
    Reads CSV header and first 3 sample rows.
    Returns:
        (column_headers, sample_rows, total_row_count)
    """
    f = io.StringIO(decoded_text)
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        raise ValueError("CSV file is empty or missing header row.")

    headers = list(reader.fieldnames)
    samples = []
    total_rows = 0

    for i, row in enumerate(reader):
        total_rows += 1
        if i < 3:
            samples.append({k: (row[k] or "").strip() for k in headers})

    return headers, samples, total_rows


def compute_ticket_hash(batch_id: str, text: str) -> str:
    """Generates SHA-256 idempotency key from batch ID and normalized text."""
    normalized = normalize_text(text)
    return hashlib.sha256(f"{batch_id}:{normalized}".encode("utf-8")).hexdigest()


def ingest_mapped_csv(
    session: Session,
    batch_id: str,
    decoded_text: str,
    mapping: dict[str, Optional[str]],
    filename: str,
    encoding_used: str,
    was_lossy: bool
) -> tuple[UploadBatch, list[Ticket], list[str]]:
    """
    Ingests CSV rows according to the operator's column mapping.
    Performs PII redaction, duplicate suppression, AI triage, and clustering.
    """
    text_col = mapping.get("complaint_text_col")
    if not text_col:
        raise ValueError("A complaint text column must be mapped.")

    channel_col = mapping.get("channel_col")
    time_col = mapping.get("timestamp_col")
    ward_col = mapping.get("ward_col")

    f = io.StringIO(decoded_text)
    reader = csv.DictReader(f)

    batch = UploadBatch(
        id=batch_id,
        filename=filename,
        total_rows=0,
        imported_rows=0,
        duplicate_rows=0,
        error_rows=0,
        encoding_detected=encoding_used,
        was_lossy=was_lossy,
        column_mapping_json=str(mapping)
    )

    created_tickets: list[Ticket] = []
    errors: list[str] = []

    from concurrent.futures import ThreadPoolExecutor

    # Step 1: Parse rows, deduplicate against DB by hash, apply PII redaction
    for row_idx, row in enumerate(reader, start=1):
        batch.total_rows += 1
        if batch.total_rows > settings.max_rows_per_batch:
            errors.append(f"Row limit exceeded at row {row_idx}. Maximum allowed: {settings.max_rows_per_batch}")
            break

        try:
            raw_complaint = (row.get(text_col) or "").strip()
            if not raw_complaint:
                batch.error_rows += 1
                errors.append(f"Row {row_idx}: Empty complaint text.")
                continue

            # Idempotency check: compute SHA-256 hash
            t_hash = compute_ticket_hash(batch_id, raw_complaint)
            from sqlmodel import select
            existing = session.exec(select(Ticket).where(Ticket.ticket_hash == t_hash)).first()
            if existing:
                batch.duplicate_rows += 1
                continue

            # Channel
            channel = (row.get(channel_col) or "CSV Upload").strip() if channel_col else "CSV Upload"

            # Locality / Ward hint
            ward_hint = (row.get(ward_col) or "").strip() if ward_col else None

            # Timestamp parsing
            timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
            if time_col and row.get(time_col):
                raw_time = row[time_col].strip()
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y"):
                    try:
                        timestamp = datetime.strptime(raw_time, fmt)
                        break
                    except ValueError:
                        pass

            # Defensive PII Redaction
            sanitized_text, redaction_meta = redact(raw_complaint)
            import json
            meta_json = json.dumps(redaction_meta) if any(redaction_meta.values()) else None

            # Create Ticket instance
            ticket = Ticket(
                batch_id=batch_id,
                ticket_hash=t_hash,
                source_channel=channel,
                raw_text=raw_complaint if settings.allow_raw_text_retention else "",
                sanitized_text=sanitized_text,
                pii_redaction_metadata=meta_json,
                ward=ward_hint,
                created_at=timestamp
            )
            created_tickets.append(ticket)

        except Exception as e:
            batch.error_rows += 1
            errors.append(f"Row {row_idx}: Failed to parse ({str(e)})")

    # Step 2: Parallel concurrent AI & Fallback triage across all rows
    if created_tickets:
        workers = min(6, len(created_tickets))

        def _safe_process(t: Ticket) -> Ticket:
            try:
                process_ticket(t)
            except Exception as ex:
                print(f"[csv_engine] Error processing ticket: {ex}", flush=True)
            return t

        with ThreadPoolExecutor(max_workers=workers) as executor:
            created_tickets = list(executor.map(_safe_process, created_tickets))

        for ticket in created_tickets:
            session.add(ticket)
            batch.imported_rows += 1

    session.add(batch)
    session.commit()

    # Refresh tickets to ensure DB IDs are populated
    for t in created_tickets:
        session.refresh(t)

    # Run Deduplication Clustering across all newly created tickets in the batch
    if len(created_tickets) >= 2:
        try:
            _, dup_links = find_duplicate_clusters(created_tickets)
            for link in dup_links:
                session.add(link)
            session.commit()
        except Exception as e:
            errors.append(f"Deduplication clustering error: {str(e)}")

    session.refresh(batch)
    return batch, created_tickets, errors
