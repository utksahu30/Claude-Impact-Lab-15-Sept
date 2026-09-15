# Bhopal Civic Triage Engine — Solo Build Plan (PS-5)

**Author's framing:** this replaces the two prior drafts, not patches them. The original plan assumed a 4–5 person team running parallel tracks; you are one person with 6–8 hours. That changes the architecture, not just the schedule. Two engines and a dual-server frontend/backend split are team-sized decisions — a solo build needs the smallest number of moving parts that can still hit every PS-5 success criterion.

---

## Changelog — second-pass review

A second review pass (the "Copilot Review" — text-identical to the earlier review this plan was already built against) was checked line-by-line against the solo plan's actual code, not just its prose. Five real gaps surfaced, all in places where the plan's narrative said one thing and the code sketch underneath did something narrower. All five are fixed in this version:

| # | Gap found | Where it lived | Fix |
|---|---|---|---|
| 1 | `AI_FAILED` was a defined state that nothing ever set — the processing loop went straight from `PROCESSING` to `NEEDS_REVIEW` on failure, so the "AI failure rate" metric in §9 was unmeasurable by construction | §6.2 processing loop | Route through `AI_FAILED` explicitly; persist a durable `ai_failed` flag + `ai_failure_reason` that survive the later transition to `NEEDS_REVIEW` |
| 2 | Deduplication blocked strictly by `category`, so two real duplicates split across a misclassified category were never even compared — despite the section's own prose claiming otherwise | §7 `find_duplicate_clusters` | Block by time window only (a real hard signal); category/ward agreement now only nudge the similarity score, never gate a comparison |
| 3 | `apply_safety_floor()` was defined but never called from the processing loop or the fallback path, and nothing stopped an operator override from silently dropping a safety-flagged urgency | §6.2, §6.3, §10 | Call the floor on both the LLM and fallback paths before persisting; require an explicit, audited reason on any override that would lower urgency below the floor |
| 4 | Tailwind and HTMX were specified as CDN-loaded, which breaks the UI on exactly the venue-wifi-drops scenario the offline fallback was built to survive; `demo_token` shipped a fixed placeholder default, published in this very document | §3 architecture, config.py, Phase 0 | Vendor both as local static files downloaded once while online; generate `demo_token` randomly at boot instead of shipping a working default |
| 5 | CSV ingestion assumed UTF-8 with lossy `errors="replace"` — silently corrupting Hindi/Hinglish text on the very common case of a Windows-1252 Excel export; §9 defined duplicate precision but never recall | §8 CSV ingestion, §9 reporting | Real encoding detection with `charset-normalizer` before any lossy fallback; added the duplicate recall definition alongside precision |

Everything else in the earlier version held up under this pass — the state machine's transition guard, the validated tool output, the precedence model's ordering, the threshold-as-config fix, and the column-mapping requirement were all already correct as designed. These five were specifically the places where a later sub-detail didn't inherit a fix that its section header implied it had.

---

## 1. What changed and why

| Decision | Team plan | Solo plan | Reason |
|---|---|---|---|
| Frontend | Next.js (separate server) + shadcn/ui | **FastAPI + Jinja2 + HTMX**, served from the same process | One process, one `uvicorn` command, zero npm build, no CORS to debug, nothing to keep in sync between two codebases. This is the single biggest time-saver for one person. |
| API client | `openapi-typescript-codegen` *or* `fetch` (plan contradicted itself) | N/A — server-rendered HTML, HTMX swaps fragments | Removes the inconsistency entirely instead of picking a side. |
| ORM | SQLAlchemy *and* SQLModel (plan named both) | **SQLModel only** | One less decision, one less thing to debug at 2am. |
| Vector store | ChromaDB, purpose never defined | **Removed.** TF-IDF (char n-grams) covers dedup at hackathon scale | The review is right that ChromaDB was never wired to anything. Don't add a dependency you can't justify in the demo. |
| Orchestration | LangChain | Direct `anthropic` SDK (unchanged — this part of the original plan was sound) | Kept. |
| Reporting | "LlamaIndex or SQL aggregations" | **SQL aggregations only**, LLM narrative paragraph as a stretch goal | LlamaIndex has no job here that SQL doesn't already do. |
| Error handling | Bare `except Exception` returning a fake-valid ticket | **Typed exceptions → `AI_FAILED` state → deterministic fallback classifier** | Fixes the review's #1 flagged risk: a failed AI call must never look like a successful one. |
| Team schedule | Parallel tracks (Frontend/Backend/AI as separate people) | **Sequential "walking skeleton" phases** — always keep an end-to-end path demoable | With one person, parallel tracks are fiction. What matters is having *something that works* at every checkpoint, in case time runs out. |

Everything else below inherits the review's fixes (state machine, PII posture, validated tool output, dedup redesign, deterministic-vs-LLM precedence) but re-scopes them to what one person can actually finish.

---

## 2. PS-5 requirements — what's actually required

Read directly from the problem statement, so scope decisions trace back to it:

- **Primary user:** the complaint-desk operator at a municipal zone office. Secondary: zone heads, department leads, field teams.
- **Problem:** complaint intake is unstructured, duplicated, manually routed — this wastes staff time on clerical work instead of follow-up. **A citizen-facing portal is explicitly out of scope.** Only the operator-facing workflow matters.
- **Inputs the engine receives:** an *already-exported* dataset — text, voice, or photo-with-caption — anonymized by the partner (names/phone/house numbers removed, dates shifted, small categories suppressed) before it reaches you. **Practical implication: you are not building a live transcription/vision pipeline.** The export already reduces every channel to text (a transcript, a caption). Build for text in, and treat live Whisper/Vision calls as a cut feature, not a stub you owe anyone.
- **Hard constraints:**
  - No write access to the helpline, municipal system, or any live channel. Export in, tables/reports out. → No integrations. Nothing "sends" anything; "approve acknowledgement" means the operator locks in a reviewed draft for the record, not a dispatch.
  - Anonymized data only, always — treat this as your baseline assumption, but add a defensive redaction pass anyway (real complaint text sometimes leaks a phone number even in an "anonymized" export).
  - Human in the loop on every acknowledgement; the engine routes, a person confirms.
  - Routing must be explainable per ticket.
- **Success criteria you're building toward:**
  1. Routing accuracy per department on a held-out test set, reported by you.
  2. Duplicate detection reduces ticket count on the test set, in line with a stated expectation.
  3. The weekly digest is usable by a zone officer *without modification* — this is a design-quality bar on the digest output, not just a data-plumbing task.
  4. The partner (or, solo, you standing in for them) can run the engine on a different week's export without code changes — this means **your CSV ingestion cannot be hardcoded to your own demo file's exact columns.** Treat this as judged, not optional.

---

## 3. Final architecture

```
Browser (HTMX + Tailwind, vendored as local static files — no build step, no CDN at runtime)
        │  HTML fragments over HTTP
        ▼
FastAPI app (single process, single port)
 ├── /upload            CSV ingestion, column mapping, validation
 ├── /tickets            queue view, filters, sort
 ├── /tickets/{id}       inspector: raw text, AI proposal, reasoning, duplicates
 ├── /tickets/{id}/override
 ├── /tickets/{id}/approve
 ├── /digest             weekly report, print-friendly, CSV export
 └── /admin/reset        reseed demo data
        │
        ├── ai_classifier.py   Anthropic tool-use call, retried, validated, timed out
        ├── fallback_classifier.py   pure-Python keyword/regex classifier (no network)
        ├── safety_rules.py    precedence: safety > human override > gazetteer > keyword > LLM > review
        ├── gazetteer.py       ward/locality fuzzy matching (rapidfuzz)
        ├── dedup.py           normalize → char n-gram TF-IDF → cosine → union-find clusters
        ├── pii.py             defensive regex redaction, never the primary control
        └── reports.py         SQL aggregations with fixed metric definitions
        │
        ▼
SQLite (WAL mode) via SQLModel — bhopal_triage.db
```

One process. One database file. One `uvicorn app.main:app` to run the whole thing on a laptop with no internet except the Anthropic API call — and even that has a fallback path.

### Repo layout

```
bhopal-triage/
  app/
    main.py
    config.py                 # pydantic Settings: model name, thresholds, flags
    models.py                 # SQLModel: Ticket, DuplicateLink, UploadBatch
    state_machine.py          # status enum + allowed transitions
    schemas.py                # Pydantic: ClassificationResult, CSV row mapping
    ai_classifier.py
    fallback_classifier.py
    safety_rules.py
    gazetteer.py
    dedup.py
    pii.py
    reports.py
    templates/
      base.html  upload.html  queue.html  ticket_detail.html  digest.html
    static/
  data/
    taxonomy.json              # partner departments/categories (hardcode a sane default)
    gazetteer.json              # ~15–20 Bhopal wards/localities + aliases
    demo_complaints.csv         # your synthetic dataset
    held_out_test.csv           # hand-labeled subset for the accuracy claim
  .env.example
  requirements.txt
  README.md
```

---

## 4. Data model and state machine

```python
# app/state_machine.py
from enum import Enum

class TicketStatus(str, Enum):
    INGESTED = "INGESTED"          # row landed from CSV, nothing done yet
    SANITIZED = "SANITIZED"        # defensive PII pass complete
    PROCESSING = "PROCESSING"      # classification in flight
    TRIAGED = "TRIAGED"            # classified with acceptable confidence
    NEEDS_REVIEW = "NEEDS_REVIEW"  # low confidence or rule/LLM conflict
    AI_FAILED = "AI_FAILED"        # API error/timeout/invalid output, retries exhausted
    APPROVED = "APPROVED"          # operator approved the ack/routing
    RESOLVED = "RESOLVED"          # operator marked done (for demo/reporting)

ALLOWED_TRANSITIONS = {
    TicketStatus.INGESTED:     {TicketStatus.SANITIZED},
    TicketStatus.SANITIZED:    {TicketStatus.PROCESSING},
    TicketStatus.PROCESSING:   {TicketStatus.TRIAGED, TicketStatus.NEEDS_REVIEW, TicketStatus.AI_FAILED},
    TicketStatus.AI_FAILED:    {TicketStatus.TRIAGED, TicketStatus.NEEDS_REVIEW},  # fallback classifier retries it
    TicketStatus.TRIAGED:      {TicketStatus.APPROVED, TicketStatus.NEEDS_REVIEW},
    TicketStatus.NEEDS_REVIEW: {TicketStatus.APPROVED},
    TicketStatus.APPROVED:     {TicketStatus.RESOLVED},
    TicketStatus.RESOLVED:     set(),
}

def can_transition(current: TicketStatus, target: TicketStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())

def transition(ticket, target: TicketStatus):
    if not can_transition(ticket.status, target):
        raise ValueError(f"Illegal transition {ticket.status} -> {target}")
    ticket.status = target
```

This single guard fixes the review's flagged bug (a fresh upload starting life as `TRIAGED`) and blocks operators from approving a ticket that never finished processing.

```python
# app/models.py
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from .state_machine import TicketStatus

class Ticket(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    batch_id: str = Field(index=True)          # traces ticket back to its CSV import
    ticket_hash: str = Field(index=True, unique=True)  # idempotency key for repeated uploads
    source_channel: str
    raw_text: str                               # only if ALLOW_RAW_RETENTION=true
    sanitized_text: str
    pii_redaction_metadata: Optional[str] = None  # counts/types redacted, never the PII itself

    department: Optional[str] = Field(default=None, index=True)
    category: Optional[str] = None
    urgency: str = Field(default="MEDIUM", index=True)
    ward: Optional[str] = Field(default=None, index=True)
    confidence: float = 0.0
    reasoning_terms: Optional[str] = None       # JSON string
    ack_draft_en: Optional[str] = None
    classification_method: Optional[str] = None # "llm" | "fallback_rules" | "safety_override"
    prompt_version: Optional[str] = None

    status: TicketStatus = Field(default=TicketStatus.INGESTED, index=True)
    human_override: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    resolved_at: Optional[datetime] = None

    # Durable failure/audit flags — status moves on after a failure or an override,
    # so these are what the reporting queries in §9 actually read, not `status`.
    ai_failed: bool = Field(default=False, index=True)   # true if classify() ever failed for this ticket
    ai_failure_reason: Optional[str] = None              # "timeout" | "rate_limit" | ... — last reason only
    safety_floor_overridden: bool = Field(default=False, index=True)  # operator downgraded a safety-flagged urgency
    override_reason: Optional[str] = None                 # required text when safety_floor_overridden is set

class DuplicateLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(index=True)
    duplicate_of_cluster: str = Field(index=True)  # connected-component id, not a single "primary" ticket
    similarity_score: float
    method: str                                     # "tfidf_char_ngram"
    confirmed_by_operator: bool = False
```

```python
# app/config.py — every threshold/flag lives here, nowhere else
import secrets
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    anthropic_model: str = "claude-sonnet-4-6"     # env-overridable, never hardcoded elsewhere
    anthropic_timeout_seconds: float = 15.0
    anthropic_max_retries: int = 3
    confidence_review_threshold: float = 0.6
    duplicate_similarity_threshold: float = 0.82   # ONE number, not 0.8 in the spec and 0.85 in the code
    allow_external_ai: bool = True                 # flip false for a fully offline demo
    allow_raw_text_retention: bool = False
    demo_token: Optional[str] = None               # no shipped default — see generation logic below
    max_upload_mb: int = 10
    max_rows_per_batch: int = 2000

    class Config:
        env_file = ".env"

settings = Settings()

# No fixed default token ships in code or in this document — a placeholder string published
# in a plan is a known secret before you've even written the app. If .env doesn't set one,
# generate a random token once at process start and print it so the operator can read it off
# the terminal. Anyone who needs it for the demo gets it from you, not from this file.
if settings.demo_token is None:
    settings.demo_token = secrets.token_urlsafe(16)
    print(f"[startup] No DEMO_TOKEN set — generated one for this run: {settings.demo_token}")
```

---

## 5. PII posture (defense in depth, not the primary control)

The dataset arrives already anonymized per PS-5's constraints — that's the partner's job upstream, not yours. Build one honest layer on top of that assumption, and document it as a safety net rather than a guarantee:

```python
# app/pii.py
import re

PHONE_RE = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{9}\b")
HOUSE_NO_RE = re.compile(r"\b(?:house|makan|plot)\s*(?:no\.?|number)?\s*[:\-]?\s*\d+[a-zA-Z]?\b", re.IGNORECASE)

def redact(text: str) -> tuple[str, dict]:
    counts = {"phone": 0, "house_no": 0}
    def _sub(pattern, label, s):
        counts[label] = len(pattern.findall(s))
        return pattern.sub(f"[{label.upper()}_REDACTED]", s)
    text = _sub(PHONE_RE, "phone", text)
    text = _sub(HOUSE_NO_RE, "house_no", text)
    return text, counts
```

Rules to state plainly in the README, because judges will ask:

- `raw_text` is retained only if `ALLOW_RAW_TEXT_RETENTION=true`; default is off — store `sanitized_text` only.
- `pii_redaction_metadata` stores counts/types redacted, never the redacted content.
- Names in Hindi/Hinglish and non-standard phone formats will not be reliably caught by regex — say this in the limitations slide instead of pretending otherwise.
- `ALLOW_EXTERNAL_AI` gates every call to Anthropic; when false, the engine runs entirely on the deterministic fallback classifier — this is also your offline-demo insurance policy.
- No raw complaint text goes into logs. Log ticket IDs and status transitions, not content.

---

## 6. AI triage engine

### 6.1 Validated structured output

The tool schema alone doesn't guarantee anything — validate what comes back.

```python
# app/schemas.py
from pydantic import BaseModel, Field
from typing import Literal

class ClassificationResult(BaseModel):
    department: str
    category: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning_terms: list[str]
    ward: str
    urgency: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    ack_draft_en: str
```

### 6.2 The call — typed exceptions, not a catch-all

This is the direct fix for the review's most serious flag: the old code returned `{"error": ..., "department": "UNASSIGNED", "urgency": "MEDIUM"}` from inside an `except Exception`, which is a partially-valid-looking result masking a real failure, and could leak exception internals. Separate the concerns: the classifier either succeeds with a *validated* result, or it raises — the caller decides what state that becomes.

```python
# app/ai_classifier.py
import time
import anthropic
from pydantic import ValidationError
from .config import settings
from .schemas import ClassificationResult

class ClassificationFailed(Exception):
    def __init__(self, reason: str):
        self.reason = reason  # "timeout" | "rate_limit" | "connection" | "invalid_output" | "no_tool_call"

client = anthropic.Anthropic(timeout=settings.anthropic_timeout_seconds)

def classify(raw_text: str, taxonomy_context: str, prompt_version: str) -> ClassificationResult:
    if not settings.allow_external_ai:
        raise ClassificationFailed("external_ai_disabled")

    last_exc = None
    for attempt in range(settings.anthropic_max_retries):
        try:
            response = client.messages.create(
                model=settings.anthropic_model,
                max_tokens=1024,
                system=f"You are a Bhopal civic triage engine. Use only this taxonomy:\n{taxonomy_context}",
                messages=[{"role": "user", "content": raw_text}],
                tools=[CLASSIFICATION_TOOL],
                tool_choice={"type": "tool", "name": "triage_complaint"},
            )
        except anthropic.APITimeoutError as e:
            last_exc = e; time.sleep(2 ** attempt); continue
        except anthropic.RateLimitError as e:
            last_exc = e; time.sleep(2 ** attempt * 2); continue
        except anthropic.APIConnectionError as e:
            last_exc = e; time.sleep(2 ** attempt); continue
        except anthropic.APIStatusError as e:
            raise ClassificationFailed(f"api_status_{e.status_code}") from e

        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if len(tool_calls) != 1:
            raise ClassificationFailed("no_tool_call" if not tool_calls else "multiple_tool_calls")
        try:
            result = ClassificationResult.model_validate(tool_calls[0].input)
        except ValidationError as e:
            raise ClassificationFailed("invalid_output") from e
        return result

    raise ClassificationFailed("retries_exhausted") from last_exc
```

Note what this does *not* do: it never logs `raw_text` on failure, never puts exception internals into the ticket record, and never returns a fake-successful shape. The caller is what decides the next state:

```python
# in the processing loop
try:
    result = classify(ticket.sanitized_text, taxonomy_context, prompt_version="v1")
    ticket.classification_method = "llm"
    apply_safety_floor(ticket.sanitized_text, result)   # §6.3 rule 1 must run before ANY result is persisted
    apply_result(ticket, result)
    transition(ticket, TicketStatus.NEEDS_REVIEW if result.confidence_score < settings.confidence_review_threshold else TicketStatus.TRIAGED)
except ClassificationFailed as e:
    # Persist the failure as real state before moving on — this is what §9's "AI failure rate"
    # metric actually queries. A status that flows straight through to NEEDS_REVIEW without ever
    # touching AI_FAILED makes that metric permanently read zero regardless of how often calls fail.
    transition(ticket, TicketStatus.AI_FAILED)
    ticket.ai_failed = True
    ticket.ai_failure_reason = e.reason
    log_processing_event(ticket.id, "ai_failed", reason=e.reason)  # no ticket content in the log

    fallback_result = fallback_classify(ticket.sanitized_text)  # pure Python, always available
    ticket.classification_method = "fallback_rules"
    apply_safety_floor(ticket.sanitized_text, fallback_result)  # the fallback path needs the floor too —
                                                                  # KEYWORD_MAP hardcodes urgency="MEDIUM" and
                                                                  # never sees this text otherwise
    apply_result(ticket, fallback_result)
    transition(ticket, TicketStatus.NEEDS_REVIEW)  # fallback output always goes to human review
```

A ticket that fails AI classification still gets a routing proposal (from the deterministic classifier) and is never silently dropped — it just always lands in `NEEDS_REVIEW`, tagged so the "Fallback Rules Active" badge can show in the UI. `ticket.ai_failed` stays `true` on the record even after the status moves past `AI_FAILED`, so "how often did the AI actually fail" remains answerable after the fact — that's the field the reporting query in §9 reads, not the current `status`.

### 6.3 Precedence model (fixes rule-vs-LLM conflicts)

```
1. Safety-critical keyword rules   (e.g. "fire", "electrocution", "gas leak" → urgency floor = CRITICAL, never downgraded by the model)
2. Human override                  (an operator's prior decision on a linked/duplicate ticket wins)
3. Gazetteer/taxonomy normalization (ward/department names get corrected regardless of source)
4. Deterministic keyword classifier (used only when AI is unavailable or invalid)
5. LLM classification
6. Manual review                   (confidence below threshold, or steps 1 and 5 disagree on urgency)
```

```python
# app/safety_rules.py
SAFETY_KEYWORDS = {"fire", "aag", "electrocution", "bijli ka jhatka", "gas leak", "building collapse", "girne wali"}

def contains_safety_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in SAFETY_KEYWORDS)

def apply_safety_floor(text: str, result) -> None:
    if contains_safety_keyword(text) and result.urgency in ("MEDIUM", "LOW"):
        result.urgency = "CRITICAL"
        result.reasoning_terms = list(set(result.reasoning_terms) | {"safety_rule_override"})
```

**The floor has to run on every code path that can set or change urgency, not just the LLM path** — defining it once and calling it from only one place is how it silently stops applying. Three call sites, all mandatory:

1. After a successful LLM classification (§6.2, before the result is persisted).
2. After the deterministic fallback classifier — `fallback_classify` hardcodes `urgency="MEDIUM"` and never sees the safety keyword list on its own, so without this call a fallback-routed "fire" complaint stays at MEDIUM.
3. **On the operator override endpoint.** The precedence list ranks "safety-critical rules" above "human override" on purpose — but ranking it above doesn't enforce anything by itself if the override form just writes whatever the operator picks straight to the DB. Don't hard-block a human from ever lowering urgency (operators have context a keyword match doesn't — "small controlled fire drill, not urgent" is a real case), but don't let it happen silently either:

```python
# in the override endpoint
if contains_safety_keyword(ticket.sanitized_text) and new_urgency in ("MEDIUM", "LOW") and ticket.urgency == "CRITICAL":
    if not override_reason or not override_reason.strip():
        raise HTTPException(422, "A reason is required to lower urgency on a safety-flagged ticket.")
    ticket.safety_floor_overridden = True
    ticket.override_reason = override_reason
ticket.urgency = new_urgency
ticket.human_override = True
```

This makes a safety-floor downgrade a distinct, audited action (`safety_floor_overridden = true`, with a mandatory reason) instead of a one-click dropdown change indistinguishable from correcting a wrong department — and it's a trivial addition to the override-rate metric in §9: report `safety_floor_overridden` counts separately, since a judge asking "can an operator quietly downgrade a fire complaint?" deserves a better answer than "technically no one stopped them."

### 6.4 Deterministic fallback classifier

This is not a lesser feature — it's what makes the offline/no-network demo credible, and it's what the accuracy claim can be honestly compared against as a baseline.

```python
# app/fallback_classifier.py — pure Python, zero network calls, always available
KEYWORD_MAP = {
    "water": ("Water Supply", "Supply Interruption"),
    "paani": ("Water Supply", "Supply Interruption"),
    "pipe": ("Water Supply", "Pipe Burst"),
    "garbage": ("Sanitation", "Waste Collection"),
    "kachra": ("Sanitation", "Waste Collection"),
    "streetlight": ("Electricity", "Streetlight Outage"),
    "pothole": ("Roads", "Pothole"),
    "sewage": ("Drainage", "Sewage Overflow"),
    # extend from the taxonomy file, not hardcoded prose
}

def fallback_classify(text: str):
    lowered = text.lower()
    for kw, (dept, cat) in KEYWORD_MAP.items():
        if kw in lowered:
            return ClassificationResult(
                department=dept, category=cat, confidence_score=0.4,
                reasoning_terms=[kw], ward="UNKNOWN", urgency="MEDIUM",
                ack_draft_en="Your complaint has been logged and will be reviewed by our team.",
            )
    return ClassificationResult(
        department="UNASSIGNED", category="Unclassified", confidence_score=0.0,
        reasoning_terms=[], ward="UNKNOWN", urgency="MEDIUM",
        ack_draft_en="Your complaint has been logged and will be reviewed by our team.",
    )
```

### 6.5 Ward normalization

```python
# app/gazetteer.py
from rapidfuzz import process, fuzz
import json

GAZETTEER = json.load(open("data/gazetteer.json"))  # {"canonical_ward": ["alias1", "alias2", ...]}
ALIAS_TO_WARD = {alias.lower(): ward for ward, aliases in GAZETTEER.items() for alias in aliases + [ward]}

def normalize_ward(raw: str, threshold: int = 85) -> str | None:
    match = process.extractOne(raw.lower(), ALIAS_TO_WARD.keys(), scorer=fuzz.WRatio)
    if match and match[1] >= threshold:
        return ALIAS_TO_WARD[match[0]]
    return None
```

---

## 7. Deduplication

Rebuilt per the review's list of problems (word-level TF-IDF with English stopwords doesn't work on Hindi/Hinglish; exact ward+category grouping misses real duplicates; one-way links instead of clusters; no explainability).

```python
# app/dedup.py
import re, unicodedata
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .config import settings

def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = re.sub(r"(?:\+?91[\s-]?)?[6-9]\d{9}", "<phone>", s)  # phone numbers don't help similarity
    return s

class UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}
    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

def find_duplicate_clusters(tickets: list) -> dict[int, str]:
    """
    tickets: list of objects with .id, .raw_text, .ward, .category, .created_at
    Returns {ticket_id: cluster_id}.

    Blocking is by TIME WINDOW ONLY (a real duplicate is the same incident reported close
    together in time — that's a much safer hard filter than category or ward, both of which
    are fields the AI or fallback classifier can simply get wrong). Category and ward agreement
    only nudge the similarity score; they never gate a comparison. The earlier version of this
    function blocked on `category` first, which meant a duplicate pair split across two different
    (mis)classified categories was never even compared — fixed here.

    At hackathon scale (tens to a few hundred rows) all-pairs TF-IDF is trivial; this doesn't
    need to scale further for a one-day demo. If a real partner export runs into the thousands
    of rows, reintroduce a coarse block (e.g. by week) before doing this — not by category/ward.
    """
    uf = UnionFind([t.id for t in tickets])
    if len(tickets) < 2:
        return {tid: str(tid) for tid in uf.parent}

    texts = [normalize_text(t.raw_text) for t in tickets]
    # char n-grams: robust to spelling variation and transliteration, unlike word tokens
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    matrix = vectorizer.fit_transform(texts)
    sim = cosine_similarity(matrix)

    for i in range(len(tickets)):
        for j in range(i + 1, len(tickets)):
            within_window = abs((tickets[i].created_at - tickets[j].created_at).days) <= 3
            if not within_window:
                continue  # the only hard filter — category/ward never disqualify a pair

            score = sim[i, j]
            if tickets[i].category and tickets[i].category == tickets[j].category:
                score += 0.03   # soft bonus, not a gate
            if tickets[i].ward and tickets[i].ward == tickets[j].ward:
                score += 0.03

            if score >= settings.duplicate_similarity_threshold:
                uf.union(tickets[i].id, tickets[j].id)

    return {tid: str(uf.find(tid)) for tid in uf.parent}
```

Every duplicate link is stored with its similarity score and method (`DuplicateLink` above), and duplicates are **advisory only** — they show as a badge with a "confirm duplicate" action in the ticket inspector, they never auto-merge or auto-close a ticket.

---

## 8. CSV ingestion — the criterion that's easy to accidentally fail

Success criterion #4 is "the partner confirms it would run the engine on the previous week's export." If your upload endpoint expects five exact hardcoded column names, that's a no on demo day the moment the columns don't match. Two things matter:

1. **Column mapping, not column assumptions.** After upload, show a one-time mapping step: "which column is the complaint text? the channel? the timestamp? the locality?" Store the mapping per batch. This is the single highest-leverage feature for that specific success criterion — prioritize it over polish features if you're short on time.
2. **Validate before you trust:** max file size (`settings.max_upload_mb`), required-columns check *after* mapping (not before), real encoding detection (below — don't blindly assume UTF-8), row cap (`settings.max_rows_per_batch`), per-row hash (`ticket_hash = sha256(batch_id + normalized_text)`) so re-uploading the same file doesn't double-insert, and a per-row error list surfaced in the UI instead of aborting the whole batch on one bad row.

**Encoding: detect it, don't assume it.** A CSV exported from Excel in India is very often Windows-1252/cp1252, not UTF-8 — and blindly decoding as UTF-8 with `errors="replace"` doesn't just lose a few accented characters, it silently mangles every Devanagari character in the Hindi/Hinglish complaint text into replacement glyphs, on exactly the export this tool exists to handle. Detect before decoding, and only fall back to lossy replacement as a last resort with a visible warning:

```python
# app/main.py — encoding detection on upload
from charset_normalizer import from_bytes

def decode_csv_bytes(raw: bytes) -> tuple[str, str, bool]:
    """Returns (decoded_text, encoding_used, was_lossy)."""
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding), encoding, False
        except UnicodeDecodeError:
            continue
    best = from_bytes(raw).best()  # charset-normalizer: detects the actual encoding
    if best is not None:
        return str(best), best.encoding, False
    return raw.decode("utf-8", errors="replace"), "utf-8 (lossy fallback)", True
```

Surface `encoding_used` and `was_lossy` in the upload confirmation UI (`app/templates/upload.html`) — if the fallback path fired, the operator sees it immediately instead of finding out later that half the Hindi text on a batch is question marks. `<meta charset="utf-8">` in `base.html` covers the app's own output; it does nothing for bytes coming in on an upload, which is the actual risk here.

```python
def compute_ticket_hash(batch_id: str, text: str) -> str:
    import hashlib
    return hashlib.sha256(f"{batch_id}:{normalize_text(text)}".encode()).hexdigest()
```

---

## 9. Reporting — precise metric definitions

The review is right that "median resolution time" is meaningless until you say what it's measured over. Fix it once, in `reports.py`, and don't let the digest template redefine it differently:

- **Resolution time** = `resolved_at - created_at`, computed **only for tickets in `RESOLVED` status**. Never-resolved tickets are excluded, not treated as zero.
- **Median** is per-department, over resolved tickets in the reporting window only.
- **Reopened tickets**: out of scope for the MVP (no reopen action exists) — say so rather than inventing a definition.
- **Routing accuracy** denominator = tickets in the held-out test set with a ground-truth label; numerator = tickets where `department` matches ground truth. Report separately for `classification_method = llm` vs `fallback_rules` — this is a much stronger demo point than one blended number.
- **Override rate** = `human_override = true` tickets ÷ all triaged tickets in the window. Report **`safety_floor_overridden = true`** as its own line, separately — an operator correcting a wrong department and an operator downgrading a safety-flagged urgency are very different events for a judge to hear about.
- **AI failure rate** = tickets where **`ai_failed = true`** ÷ all tickets processed in the window — query the durable flag, not `status`. `status` moves a failed ticket on to `NEEDS_REVIEW` after the fallback classifier runs, so a query against current `status == AI_FAILED` will always read close to zero regardless of how often the API actually failed; `ai_failed` is set once and never cleared, so it stays queryable after the fact.
- **Duplicate precision** = correctly-flagged pairs ÷ total flagged pairs, on your labeled held-out set (the pairs you planted on purpose). Report it, even if it's a small sample; don't claim a number you haven't computed.
- **Duplicate recall** = correctly-flagged pairs ÷ total true-duplicate pairs that actually exist in that held-out set. Report precision and recall together, not just one — a pass that only flags the three most obvious duplicates (high precision, low recall) is a materially different result from one that over-flags and needs a lot of operator "not a duplicate" clicks (low precision, high recall), and a judge asking "how good is the dedup, really?" is asking for both numbers, not one. If you haven't measured either, write "target" not a result — this is the direct fix for the review's flag on the unverified "92% Top-1 Accuracy" claim.

CSV export: prefix any cell starting with `= + - @` with a single quote before writing, to close the formula-injection hole the review flagged.

---

## 10. UI — states the happy-path plan forgot

Minimum states to actually build (HTMX makes each of these a small template partial, not a new page):

- Upload in progress / partial import success / per-row failures listed
- AI processing (spinner + count) / AI failure badge ("Fallback Rules Active")
- Low-confidence review flag
- Duplicate-review pending badge
- Empty queue state
- Network/API disconnected banner (ties directly into `allow_external_ai` and the fallback path — this is your resilience demo, make it visible, not just functional)

Operator workflow, in the ticket inspector:
- Left: raw complaint (sanitized), channel, timestamp.
- Right: AI (or fallback) proposal — department, category, ward, urgency, confidence, **reasoning terms highlighted inline in the raw text** (this is the cheapest high-impact "explainability" feature — highlighting the words that drove the decision reads as far more sophisticated than it is to build).
- "Why this routing?" panel: matched terms, which safety rule fired (if any), model confidence, whether a human changed it.
- Duplicate cluster badge with linked tickets, "confirm duplicate" action.
- Override dropdowns (department/category/ward/urgency), sets `human_override = true` on save.
- Ack draft textarea + "Approve" button → `transition(ticket, APPROVED)`.

Auth: bind to `127.0.0.1` by default; if you demo over a shared network, require a header token matching `settings.demo_token` on all non-GET routes. That token is generated randomly at process start (or set explicitly in `.env`) — never a fixed value baked into the code, since a default published in a project plan is a default a judge (or anyone else) can also read. No `/admin` route reachable without it; no login system otherwise.

---

## 11. Solo execution schedule — walking skeleton, not parallel tracks

The organizing idea: **have an end-to-end demoable path within the first 90 minutes**, then layer sophistication on top of it in vertical slices. If you run out of time at hour 6 instead of hour 8, you still have a working demo — you just cut fewer of the "why this is good" details, not the core path.

At the end of every phase there's a **bar to clear before moving on**, and a **cut list if you're behind**.

| Phase | Time | Build | Bar to move on | If behind, cut |
|---|---|---|---|---|
| **0. Setup** | 0:00–0:30 | Repo, venv, `requirements.txt`, `.env.example`, `config.py`, empty FastAPI app returning "ok", taxonomy.json + gazetteer.json seeded with ~10 depts and ~15 wards, synthetic demo CSV (~40 rows) + a held-out labeled subset (~15–20 rows). **While you still have internet: download HTMX and Tailwind's CDN script once into `app/static/` and reference them locally from here on** — this is the cheapest possible fix for a UI that would otherwise go blank the moment venue wifi drops, and it takes thirty seconds now versus a scramble later | `uvicorn app.main:app` runs, taxonomy/gazetteer files exist, `app/static/htmx.min.js` and the Tailwind asset exist on disk | Trim gazetteer to 8 wards |
| **1. Walking skeleton** | 0:30–1:30 | `Ticket` model, DB init (WAL + indexes), upload endpoint (hardcoded columns is fine here), `fallback_classify` wired as the *only* classifier for now, queue template listing tickets | You can upload the demo CSV and see a populated table in the browser | Skip styling entirely, raw HTML table |
| **2. AI triage** | 1:30–3:00 | `ClassificationResult`, `ai_classifier.classify` with retry/timeout/typed exceptions, safety rule precedence, wire real LLM into the processing loop with fallback-on-failure, gazetteer fuzzy ward matching | A ticket processed by the LLM shows real department/urgency/confidence; killing the API key still produces `NEEDS_REVIEW` tickets via fallback, not a crash | Skip gazetteer fuzzy matching, use exact match only |
| **3. Operator workflow** | 3:00–4:00 | Ticket inspector page, reasoning-term highlighting, override controls, ack approve button, state-machine guard enforced on every transition, demo-token auth on writes | You can open a ticket, see why it was routed, override it, approve it, and the DB status updates correctly | Skip inline highlighting, just list reasoning terms as text |
| **4. Deduplication** | 4:00–5:15 | `normalize_text`, char n-gram TF-IDF, union-find clustering, `DuplicateLink` records, duplicate badge + confirm action in UI | Running dedup on the demo CSV (which should contain 3–5 planted near-duplicates) correctly clusters them | Ship word-level TF-IDF as an interim step, upgrade to char n-grams only if time remains |
| **5. Column mapping** | 5:15–5:45 | One-time mapping UI step so upload isn't hardcoded to your demo file's headers | You can re-upload the demo CSV with renamed columns and it still ingests correctly after mapping | If truly out of time, hardcode columns but say so explicitly in the "known limitations" slide — this directly affects success criterion #4, don't cut it silently |
| **6. Reporting** | 5:45–6:45 | Aggregation queries with the metric definitions above, digest template with print CSS, CSV export with formula-injection escaping | Digest renders correctly for the demo dataset and looks presentable printed | Cut the LLM narrative paragraph stretch goal first |
| **7. Evaluation** | 6:45–7:15 | Run the held-out set through the full pipeline, compute per-department accuracy (llm vs fallback separately), duplicate precision/recall on the planted duplicates, write numbers into README as *measured*, not claimed | You have real numbers, even modest ones, that you can defend if a judge asks how you got them | If numbers are bad, report them anyway with a one-line diagnosis — that reads better to judges than a suspiciously round 92% |
| **8. Hardening & demo prep** | 7:15–7:45 | "Reset Demo Data" endpoint, verify `ALLOW_EXTERNAL_AI=false` path works end to end **and** disconnect wifi entirely to confirm the UI still renders correctly from vendored static files (not just that the AI fallback works — a styled-but-broken page is still a bad demo), README with architecture/limitations/numbers, 2-minute demo script | Demo runs twice in a row, fully offline, without manual DB surgery | Cut keyboard shortcuts, confidence heatmap coloring — visual-only polish |
| **9. Freeze** | 7:45–8:00 | No new commits except bug fixes found in rehearsal | — | — |

### Explicit stretch list (only if every phase above finished early)
- Hindi acknowledgement generation as a second, separate LLM call (keep it out of the critical triage path per the review's own suggestion).
- Emerging-cluster alert (`COUNT(category, ward, 24h) > N` → toast).
- LLM-generated narrative paragraph for the digest.
- Confidence heatmap coloring in the queue table.
- Keyboard shortcuts for approve/next.

### Explicit cut list (never build these solo, in 6–8 hours)
- Live speech-to-text or vision API calls — the export already gives you text.
- Any citizen-facing surface.
- Any write path back into a real municipal system.
- A separate frontend framework/build step.
- ChromaDB, LangChain, LlamaIndex, Presidio — each solves a problem this scope doesn't have.

---

## 12. Testing, honestly

- Hand-label the held-out subset yourself (15–20 rows is enough to report a real, if small-sample, accuracy figure — say the sample size out loud in the pitch).
- Include in the demo/test data: a few safety-critical complaints (confirm they're never downgraded), a few Hinglish/Hindi ones, a few near-duplicates across different "channels," a few that should legitimately fail classification (garbled/empty text) to prove the `AI_FAILED` path works.
- Test the state machine directly: assert illegal transitions raise.
- Test `redact()` against a handful of phone-number formats you expect to see (with and without `+91`, with spaces/dashes) and document what it misses.
- One end-to-end smoke test: upload → process → override → approve → appears correctly in the digest.

---

## 13. Known-limitations slide (prepare this, don't improvise it)

- Multi-modal intake assumes the export already contains transcribed/captioned text; no live speech or vision integration.
- PII redaction is a defensive regex layer on top of an already-anonymized export, not a certified de-identification pipeline; Hindi/Hinglish names are not reliably caught.
- Accuracy and duplicate precision are measured on a small, self-labeled held-out set (state the N), not partner-validated.
- No authentication beyond a shared demo token; intended for a trusted intranet deployment, not public internet.
- SQLite/WAL is fine for a single-writer demo; a real multi-operator deployment needs a proper server database and a migration story.

---

## 14. requirements.txt (solo-scoped, nothing unused)

```
fastapi
uvicorn[standard]
sqlmodel
jinja2
python-multipart
pandas
scikit-learn
rapidfuzz
anthropic
pydantic-settings
python-dotenv
charset-normalizer
```

No `langchain`, no `chromadb`, no `llama-index`, no Node/npm toolchain at all.

---

## 15. Highest-priority changes, re-ranked for one person

1. Get the walking skeleton (Phase 1) working before anything else — it's your insurance policy against running out of time.
2. Typed exception handling → `AI_FAILED` → deterministic fallback, wired end to end and actually tested with the API key removed.
3. The state machine guard, enforced on every write path.
4. CSV column mapping — this is the one item that directly determines whether you can honestly claim success criterion #4.
5. Char n-gram dedup with connected components, advisory-only in the UI.

Everything else in this document is real, but these five are what separates "demoable" from "impressive."
