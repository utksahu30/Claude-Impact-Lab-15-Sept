# Bhopal Civic Triage Engine (PS-5) — Architectural Handoff & Technical Guide

This document serves as the comprehensive technical reference, system specification, and architectural handoff for the **Bhopal Civic Triage Engine (PS-5)**. It is structured so that any future AI LLM, engineer, or municipal authority can understand the system in its entirety, verify its design decisions, and extend its functionality seamlessly.

---

## 1. System Overview & Problem Statement Context

### Problem Addressed (PS-5)
Municipal complaint intake across Bhopal Municipal Corporation (BMC) receives unstructured civic complaints across multiple channels (Helpline 181, WhatsApp, CM Helpline, Mobile App, Walk-in). These complaints arrive as unstructured text, contain duplicates, and are manually routed by desk operators.

### Key PS-5 Design Principles
1. **Operator-Facing Workflow**: A citizen-facing portal is explicitly out of scope. The engine is built exclusively for the complaint-desk operator and municipal zonal officers.
2. **Pre-Processed Text Intake**: The engine operates on exported datasets where speech or photos have already been transcribed or captioned.
3. **No Direct Write-Back Integrations**: By design, the engine operates read-only on raw inputs and generates structured tables, validated queues, and digests. "Approving an acknowledgement" records the approved draft internally; it does not dispatch to live telco/municipal ERP channels.
4. **Resilient Offline Architecture**: If external AI or venue network drops, the application transitions smoothly to deterministic fallback classifiers. All frontend assets (HTMX, CSS) are vendored locally in `app/static/` with zero CDN dependency.

---

## 2. Directory Structure & File Manifest

```
d:/Claude Impact Lab 15 Sep/Antigravity/
├── app/
│   ├── __init__.py
│   ├── config.py                 # Pydantic BaseSettings: Qwen 3.8 Max, thresholds, demo auth token
│   ├── db.py                     # SQLModel engine with SQLite WAL mode & connection pooling
│   ├── models.py                 # Ticket, DuplicateLink, UploadBatch database models
│   ├── state_machine.py          # TicketStatus enum, ALLOWED_TRANSITIONS guard matrix
│   ├── schemas.py                # Pydantic models: ClassificationResult, ColumnMappingRequest, TicketOverrideRequest
│   ├── ai_classifier.py          # Qwen 3.8 Max via DashScope OpenAI client, retry backoff, typed exceptions
│   ├── fallback_classifier.py    # Deterministic pure-Python keyword/regex classifier (offline resilience)
│   ├── safety_rules.py           # Safety precedence: CRITICAL urgency floor enforcement
│   ├── gazetteer.py              # Fuzzy matching & extraction against 20 Bhopal wards via RapidFuzz
│   ├── dedup.py                  # Char n-gram TF-IDF (2-4 ngrams), time-window blocking, Union-Find clustering
│   ├── pii.py                    # Defensive phone & house number regex redaction
│   ├── csv_engine.py             # Ingestion engine with charset-normalizer detection & idempotency hashing
│   ├── reports.py                # SQL aggregations with exact metric definitions & formula injection escaping
│   ├── evaluation.py             # Held-out benchmark runner comparing LLM vs fallback accuracy
│   ├── main.py                   # FastAPI application routes (queue, inspector, upload, digest, eval)
│   ├── static/
│   │   ├── htmx.min.js           # Vendored HTMX 2.0.2 (offline resilient, zero CDN)
│   │   └── style.css             # High-contrast, dark-mode CSS with responsive layout and print styles
│   └── templates/
│       ├── base.html             # Base shell, navigation bar, resilience indicator, HTMX headers
│       ├── queue.html            # Operator intake queue with status pills, badges, and quick inspect
│       ├── ticket_detail.html    # Inspector: highlighted reasoning, AI proposal, duplicate drawer, override form
│       ├── upload.html           # 2-step upload: file selection & dynamic column mapping preview
│       ├── digest.html           # Executive weekly report for zonal officers with print CSS & CSV download
│       └── eval_dashboard.html   # Live evaluation runner and breakdown on held-out dataset
├── data/
│   ├── taxonomy.json             # BMC departments, categories, keywords, and default urgency
│   ├── gazetteer.json            # 20 Bhopal wards and extensive Hindi/English locality aliases
│   ├── demo_complaints.csv       # 40 synthetic Bhopal complaints (duplicates, emergencies, Hindi/Hinglish)
│   └── held_out_test.csv         # 20 ground-truth hand-labeled benchmark complaints
├── tests/
│   ├── test_state_machine.py     # State machine transitions and transition guard tests
│   ├── test_pii.py               # Phone and house number redaction tests
│   ├── test_safety_rules.py      # Safety floor and keyword match tests
│   ├── test_dedup.py             # Char n-gram deduplication and time window tests
│   ├── test_csv_ingestion.py     # Encoding detection and idempotency tests
│   └── test_reports.py           # Formula injection escaping tests
├── .env                          # Active credentials (DashScope API key, endpoints)
├── .env.example                  # Template environment variables
├── .gitignore                    # Git ignore file
├── requirements.txt              # Pinned Python package dependencies
├── evaluate.py                   # Command-line benchmark runner
└── ARCHITECTURAL_HANDOFF.md      # This document
```

---

## 3. Core Architectural Modules

### 3.1 State Machine (`app/state_machine.py`)
To prevent invalid state jumps (e.g. approving an un-triaged ticket), a strict transition guard is enforced:

```
INGESTED ──► SANITIZED ──► PROCESSING ──┬──► TRIAGED ────────┬──► APPROVED ──► RESOLVED
                                        │                    │
                                        ├──► NEEDS_REVIEW ───┤
                                        │                    │
                                        └──► AI_FAILED ──────┘ (handled by fallback classifier)
```

`ALLOWED_TRANSITIONS` explicitly blocks illegal transitions and raises `ValueError` if violated.

### 3.2 AI Classification Engine (`app/ai_classifier.py`)
- Powered by **Qwen 3.8 Max** (`qwen3.8-max`) via the DashScope OpenAI-compatible endpoint (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`).
- Uses `response_format={"type": "json_object"}` with strict Pydantic validation via `ClassificationResult`.
- Exponential backoff retry loop (up to 3 attempts) handling `APITimeoutError`, `RateLimitError`, `APIConnectionError`.
- Raises custom typed exception `ClassificationFailed(reason)`.
- On failure:
  1. Transitions to `AI_FAILED`.
  2. Sets durable `ai_failed = True` and `ai_failure_reason` (ensuring reporting queries measure AI failure rate accurately).
  3. Executes `fallback_classifier.py` (deterministic keyword/regex matching).
  4. Runs `apply_safety_floor()`.
  5. Transitions to `NEEDS_REVIEW`.

### 3.3 Safety Precedence Model (`app/safety_rules.py`)
Precedence order:
1. **Safety-Critical Rules** (Urgency floor = `CRITICAL` for terms like fire, electrocution, live wire, gas leak, building collapse, open manhole).
2. **Human Override** (Operator decisions override model suggestions).
3. **Gazetteer Normalization** (Standardizes ward names regardless of source).
4. **Deterministic Keyword Rules** (Used on AI failure).
5. **LLM Classification** (Qwen 3.8 Max proposal).
6. **Manual Review** (Confidence < 0.6 or conflict).

**Three Mandatory Call Sites for `apply_safety_floor()`**:
- Successful LLM classification (before saving).
- Deterministic fallback path (which hardcodes `MEDIUM` urgency).
- Operator override endpoint: If an operator attempts to downgrade a safety-flagged ticket from `CRITICAL` to `MEDIUM` or `LOW`, an `override_reason` is **mandatory**. If omitted, a 422 alert is rendered. If provided, `ticket.safety_floor_overridden = True` and `ticket.override_reason` are durably recorded for municipal audit.

### 3.4 Char N-Gram Deduplication (`app/dedup.py`)
- Standard word-level tokenization fails on Hindi/Hinglish spelling variations (e.g. *paani*, *pani*, *pipeline*, *pipe line*).
- Solution: `TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))` with cosine similarity.
- **Blocking rule**: Blocking is by **time window only** (`<= 3 days`). Ward and category matches provide soft bonuses (+0.03 each) but never disqualify pairs from comparison.
- Disjoint-set union (`UnionFind`) generates connected-component cluster IDs (`cluster-<id>`).
- Duplicates are advisory: displayed with links in the inspector for operator review, never auto-merged or auto-deleted.

### 3.5 Flexible CSV Ingestion (`app/csv_engine.py`)
- **Encoding detection**: Uses `charset-normalizer` to detect UTF-8, UTF-8-sig, and Windows-1252 (common in Indian Excel exports) before lossy replacement.
- **Dynamic Column Mapping**: Supports arbitrary column names by previewing headers and sample rows to the operator.
- **Idempotency**: Calculates SHA-256 hash `sha256(batch_id + normalize_text(text))` per row, preventing duplicate insertions on re-upload.

### 3.6 Reporting & Metrics Definitions (`app/reports.py`)
- **Resolution Time**: Measured as `resolved_at - created_at` **only over tickets in `RESOLVED` status**. Unresolved tickets are excluded.
- **Median**: Calculated per-department over resolved tickets in the window.
- **AI Failure Rate**: Queries the durable `ai_failed = True` flag divided by total processed tickets.
- **Human Override Rate**: `human_override = True` divided by total triaged tickets.
- **Formula Injection Protection**: Prefixes any CSV cell starting with `=`, `+`, `-`, or `@` with a single quote `'`.

---

## 4. Skipped & Future Enhancements Overview

Per project requirements, the following features were deliberately scoped out for this solo build. This section provides detailed technical instructions so any future AI LLM or human engineer can implement them without friction.

### 4.1 Live Multimodal Intake (Speech-to-Text & Vision)
- **Status**: Skipped / Out of Scope.
- **Why**: PS-5 specifies that intake data arrives as pre-exported transcripts or captions.
- **How to Implement in the Future**:
  1. Add `faster-whisper` or OpenAI Whisper API integration in `app/csv_engine.py`.
  2. For audio files, transcribe to Hindi/English text prior to `redact()`.
  3. For photos, pass images directly to Qwen 3.8 Max's native multimodal vision capabilities via base64 encoded data URLs to extract civic issue captions.

### 4.2 Multi-Operator Role-Based Access Control (RBAC)
- **Status**: Simplified to intranet demo-token authentication (`X-Demo-Token`).
- **Why**: PS-5 is designed for single-operator intranet deployment at a municipal zonal desk.
- **How to Implement in the Future**:
  1. Create a `User` model (`id, username, hashed_password, role`) with roles (`operator`, `zonal_officer`, `admin`).
  2. Implement OAuth2 / JWT authentication in `app/auth.py` using `fastapi.security`.
  3. Restrict `/tickets/{id}/approve` and `/admin` routes based on user role.

### 4.3 Direct Municipal ERP Write-Back Integration
- **Status**: Skipped / Out of Scope.
- **Why**: PS-5 hard constraint prohibits external write access to live municipal helplines.
- **How to Implement in the Future**:
  1. Create `app/integrations/bmc_crm.py`.
  2. On `POST /tickets/{id}/approve`, dispatch an HTTP POST request with the approved JSON payload to BMC's official dispatch webhook URL.
  3. Record the external dispatch transaction ID in a new field `ticket.external_dispatch_id`.

---

## 5. Verification & Operational Commands

### Running Unit Tests
```bash
python -m pytest -v
```
All 17 automated tests verify state machine guards, defensive PII redaction, safety floor precedence, char n-gram deduplication, and formula sanitization.

### Running Held-Out Benchmark
```bash
python evaluate.py
```
Evaluates routing accuracy and duplicate recall/precision on `data/held_out_test.csv`.

### Starting the Application Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to `http://127.0.0.1:8000/tickets` to access the operator queue.
