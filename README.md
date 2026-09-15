# Bhopal Civic Triage Engine (PS-5)

A resilient, operator-facing municipal complaint triage, deduplication, and weekly digest system built for the Bhopal Municipal Corporation (BMC). Powered by **Qwen 3.8 Max** (`qwen3.8-max`) with offline-first deterministic fallback classifiers and zero-CDN frontend architecture.

---

## 🌟 Key Features

1. **AI Triage with Qwen 3.8 Max (`qwen3.8-max`)**:
   - Structured JSON output with strict Pydantic schema validation (`ClassificationResult`).
   - Exponential retry backoff, timeout handling, and typed exception boundaries (`ClassificationFailed`).
   - Extracts bilingual reasoning terms highlighted inline directly in complaint text.
2. **Resilient Deterministic Fallback Classifier**:
   - Pure-Python keyword/regex classifier with zero network dependency.
   - If external AI is disabled or fails, tickets transition cleanly through `AI_FAILED` &rarr; `fallback_rules` &rarr; `NEEDS_REVIEW` with an advisory "Fallback Rules Active" badge.
3. **Safety Precedence Guard**:
   - Immutable `CRITICAL` urgency floor for hazard terms (*fire, live wire, electrocution, gas leak, open manhole*).
   - Enforced on LLM path, fallback path, and operator overrides (requires mandatory audited reason for downgrades).
4. **Char N-Gram Deduplication**:
   - Normalization with phone masking + character n-gram TF-IDF (2-4 ngrams) and cosine similarity.
   - **Time window hard blocking only** (`<= 3 days`). Ward and category matches provide soft bonuses (+0.03 each) without gating comparisons.
   - Connected-component clustering via Disjoint Set Union (`UnionFind`). Duplicates are advisory and never auto-merged.
5. **Flexible CSV Ingestion & Encoding Detection**:
   - Automated encoding detection via `charset-normalizer` (safeguards Devanagari/Hindi text on Windows-1252 Excel exports).
   - Dynamic 2-step column mapping allowing the engine to ingest arbitrary municipal export schemas without code changes.
   - SHA-256 idempotency hash per row (`ticket_hash = sha256(batch_id + normalized_text)`) preventing duplicate insertions on re-upload.
6. **Zero-CDN Operator Dashboard**:
   - Vendored HTMX and modern high-contrast CSS in `app/static/` for complete venue-wifi drop resilience.
   - Real-time queue filters, inspector with inline reasoning highlights, and 1-click acknowledgement approvals.
   - Executive weekly report (`/digest`) with print CSS and formula-injection-safe CSV exports.
   - Live evaluation dashboard (`/eval`) running against held-out benchmark datasets.

---

## 🚀 Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env` and verify your credentials:
```ini
DASHSCOPE_API_KEY=your_dashscope_api_key_here
DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3.8-max
ALLOW_EXTERNAL_AI=True
CONFIDENCE_REVIEW_THRESHOLD=0.6
DUPLICATE_SIMILARITY_THRESHOLD=0.82
```

### 3. Run Automated Tests
```bash
python -m pytest -v
```
All 17 tests verify state machine guards, PII redaction, safety floor precedence, deduplication clustering, and CSV formula sanitization.

### 4. Run Evaluation Benchmark
```bash
python evaluate.py
```

### 5. Launch the Web Server
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open your browser at [http://127.0.0.1:8000/tickets](http://127.0.0.1:8000/tickets).

---

## 📋 PS-5 Success Criteria Scorecard

| # | Criterion | Implementation | Status |
|---|---|---|---|
| 1 | **Routing accuracy per department** | Measured on held-out benchmark (`data/held_out_test.csv`), reported separately for Qwen 3.8 Max vs Fallback rules. | ✅ Verified |
| 2 | **Duplicate detection reduces count** | Char n-gram TF-IDF clustering on near-duplicates within 3-day time window; advisory cluster links surfaced in UI. | ✅ Verified |
| 3 | **Digest usable by Zonal Officer without modification** | Clean print CSS (`@media print`), SLA compliance, median resolution times (resolved only), safety downgrade audit log, CSV export. | ✅ Verified |
| 4 | **Partner can run on arbitrary week's export** | Dynamic column mapping interface with `charset-normalizer` encoding detection (UTF-8 & Windows-1252). | ✅ Verified |

---

## 🔒 Defensive PII Posture

- **Baseline Assumption**: Exported data is already de-identified upstream by the municipal partner.
- **Defense in Depth**: Defensive regex layer masks Indian phone numbers (`+91 9XXXXXXXXX`) and house/plot numbers before storage.
- **Audit**: Redaction counts are recorded in `pii_redaction_metadata`; raw PII strings are never logged or persisted unless `ALLOW_RAW_TEXT_RETENTION=True` is explicitly toggled.

---

## 📖 Architectural Handoff

For in-depth architectural details, database schemas, state transition matrices, and instructions on extending the platform, refer to [`ARCHITECTURAL_HANDOFF.md`](./ARCHITECTURAL_HANDOFF.md).
