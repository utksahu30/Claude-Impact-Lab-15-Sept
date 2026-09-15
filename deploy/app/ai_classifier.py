# app/ai_classifier.py
import json
import time
from pathlib import Path
from typing import Optional
from openai import OpenAI, APITimeoutError, RateLimitError, APIConnectionError, APIStatusError
from pydantic import ValidationError

from .config import settings
from .models import Ticket
from .schemas import ClassificationResult
from .state_machine import TicketStatus, transition
from .safety_rules import apply_safety_floor
from .fallback_classifier import fallback_classify
from .gazetteer import normalize_ward, extract_ward_from_text


class ClassificationFailed(Exception):
    """Custom typed exception for triage failure tracking."""
    def __init__(self, reason: str):
        super().__init__(f"Classification failed: {reason}")
        self.reason = reason  # "external_ai_disabled", "timeout", "rate_limit", "connection", "invalid_output", "retries_exhausted", "api_status_*"


# Load taxonomy for system prompt context
TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "taxonomy.json"
try:
    with open(TAXONOMY_PATH, "r", encoding="utf-8") as f:
        TAXONOMY_DATA = json.load(f)
        TAXONOMY_CONTEXT = json.dumps(TAXONOMY_DATA, ensure_ascii=False, indent=2)
except Exception:
    TAXONOMY_CONTEXT = "Standard Bhopal Municipal Taxonomy: Water Supply, Sanitation, Electricity, Roads & Infrastructure, Drainage & Sewage, Stray Animals, Public Health, Encroachment."


SYSTEM_PROMPT = f"""You are the Bhopal Civic Triage Engine. Analyze incoming civic complaints from Bhopal citizens (in English, Hindi, or Hinglish).
Route each complaint accurately based strictly on this municipal taxonomy:
{TAXONOMY_CONTEXT}

Output MUST be a single valid JSON object with EXACTLY the following structure:
{{
  "department": "Name of Municipal Department",
  "category": "Specific category under department",
  "confidence_score": 0.95,
  "reasoning_terms": ["list", "of", "matched", "keywords", "from", "text"],
  "ward": "Bhopal Ward or Locality (e.g. MP Nagar, Arera Colony, Kolar, or UNKNOWN)",
  "urgency": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
  "ack_draft_en": "Polite English acknowledgement draft informing the citizen of the department and estimated SLA.",
  "ack_draft_hi": "विनम्र हिंदी पावती प्रारूप नागरिक को सूचित करते हुए कि उनकी शिकायत संबंधित विभाग को भेज दी गई है।"
}}

CRITICAL INSTRUCTIONS:
1. Urgency: If the complaint involves life-threatening hazards (fire, live electric wire, open transformer, gas leak, building collapse, open manhole), urgency MUST be "CRITICAL".
2. Ward: Normalize to standard Bhopal localities (e.g., MP Nagar, Arera Colony, Kolar Road, Shahpura, TT Nagar, Bairagarh, Karond, Govindpura, Old Bhopal).
3. Confidence: Rate between 0.0 and 1.0. If ambiguous, provide a lower score.
4. Reasoning terms: Include the exact keywords or phrases from the complaint that led to the routing decision.
"""


def get_openai_client() -> OpenAI:
    """Instantiates the OpenAI client configured for Qwen 3.8 Max or custom base URL."""
    return OpenAI(
        api_key=settings.dashscope_api_key or "sk-placeholder",
        base_url=settings.dashscope_base_url,
        timeout=settings.ai_timeout_seconds
    )


def classify(raw_text: str, prompt_version: str = "v1") -> ClassificationResult:
    """
    Calls Qwen 3.8 Max with timeout, retries, and strict schema validation.
    Raises ClassificationFailed on any network or validation error.
    """
    if not settings.allow_external_ai:
        raise ClassificationFailed("external_ai_disabled")

    if not settings.dashscope_api_key:
        raise ClassificationFailed("missing_api_key")

    client = get_openai_client()
    last_exc: Optional[Exception] = None

    for attempt in range(settings.ai_max_retries):
        try:
            response = client.chat.completions.create(
                model=settings.qwen_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Analyze and classify this civic complaint:\n\n{raw_text}"}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )

            raw_content = response.choices[0].message.content
            if not raw_content:
                raise ClassificationFailed("empty_response")

            data = json.loads(raw_content)
            result = ClassificationResult.model_validate(data)
            return result

        except APITimeoutError as e:
            last_exc = e
            time.sleep(1.5 ** attempt)
            continue
        except RateLimitError as e:
            last_exc = e
            time.sleep(2.0 ** attempt * 2)
            continue
        except APIConnectionError as e:
            last_exc = e
            time.sleep(1.5 ** attempt)
            continue
        except APIStatusError as e:
            raise ClassificationFailed(f"api_status_{e.status_code}") from e
        except (json.JSONDecodeError, ValidationError) as e:
            raise ClassificationFailed("invalid_output") from e
        except Exception as e:
            raise ClassificationFailed(f"unexpected_error_{type(e).__name__}") from e

    raise ClassificationFailed("retries_exhausted") from last_exc


def apply_classification_result(ticket: Ticket, result: ClassificationResult) -> None:
    """Applies validated classification output onto the Ticket model."""
    ticket.department = result.department
    ticket.category = result.category
    ticket.confidence = result.confidence_score
    ticket.reasoning_terms = json.dumps(result.reasoning_terms, ensure_ascii=False)
    
    # Ward normalization via gazetteer
    normalized_ward = normalize_ward(result.ward) or extract_ward_from_text(ticket.sanitized_text) or result.ward
    ticket.ward = normalized_ward
    ticket.urgency = result.urgency
    ticket.ack_draft_en = result.ack_draft_en
    ticket.ack_draft_hi = result.ack_draft_hi


def process_ticket(ticket: Ticket, prompt_version: str = "v1") -> None:
    """
    Executes the full triage processing loop with state machine transitions,
    resilient fallback to deterministic rules, and safety floor enforcement.
    """
    # 1. Transition to PROCESSING
    if ticket.status == TicketStatus.INGESTED:
        transition(ticket, TicketStatus.SANITIZED)
    if ticket.status == TicketStatus.SANITIZED:
        transition(ticket, TicketStatus.PROCESSING)

    # 2. Attempt LLM classification
    try:
        result = classify(ticket.sanitized_text, prompt_version=prompt_version)
        ticket.classification_method = "llm"
        ticket.prompt_version = prompt_version
        
        # Enforce safety floor before persisting
        apply_safety_floor(ticket.sanitized_text, result)
        apply_classification_result(ticket, result)

        # Transition based on confidence threshold
        if result.confidence_score < settings.confidence_review_threshold:
            transition(ticket, TicketStatus.NEEDS_REVIEW)
        else:
            transition(ticket, TicketStatus.TRIAGED)

    except ClassificationFailed as e:
        # Route through AI_FAILED explicitly and persist durable audit flags
        transition(ticket, TicketStatus.AI_FAILED)
        ticket.ai_failed = True
        ticket.ai_failure_reason = e.reason

        # Fallback to pure-Python deterministic classifier
        fallback_res = fallback_classify(ticket.sanitized_text, ward_hint=ticket.ward)
        ticket.classification_method = "fallback_rules"
        ticket.prompt_version = "fallback_v1"
        
        # Enforce safety floor on fallback path too
        apply_safety_floor(ticket.sanitized_text, fallback_res)
        apply_classification_result(ticket, fallback_res)

        # Fallback tickets always route to human review
        transition(ticket, TicketStatus.NEEDS_REVIEW)
