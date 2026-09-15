# app/safety_rules.py
from typing import Any

SAFETY_KEYWORDS = {
    "fire",
    "aag",
    "electrocution",
    "bijli ka jhatka",
    "gas leak",
    "cylinder blast",
    "building collapse",
    "girne wali",
    "open transformer",
    "exposed wire",
    "live wire",
    "current aa raha",
    "khula manhole",
    "open manhole",
    "manhole cover missing"
}


def contains_safety_keyword(text: str) -> bool:
    """Checks if the given text contains any safety-critical emergency keyword."""
    if not text:
        return False
    lowered = text.lower()
    return any(keyword in lowered for keyword in SAFETY_KEYWORDS)


def get_matched_safety_keywords(text: str) -> list[str]:
    """Returns the list of safety keywords detected in the text."""
    if not text:
        return []
    lowered = text.lower()
    return [kw for kw in SAFETY_KEYWORDS if kw in lowered]


def apply_safety_floor(text: str, result: Any) -> None:
    """
    Enforces the CRITICAL safety floor.
    Must be called on:
      1. LLM classification path (before persisting)
      2. Fallback classifier path (which defaults to MEDIUM)
      3. Operator override endpoint (audited downgrade enforcement)
    """
    if not contains_safety_keyword(text):
        return

    # Handle both Pydantic models/dataclasses and dicts
    current_urgency = getattr(result, "urgency", None) or (result.get("urgency") if isinstance(result, dict) else None)
    
    if current_urgency != "CRITICAL":
        if hasattr(result, "urgency"):
            result.urgency = "CRITICAL"
        elif isinstance(result, dict):
            result["urgency"] = "CRITICAL"

        matched = get_matched_safety_keywords(text)
        override_term = "safety_rule_override"

        if hasattr(result, "reasoning_terms"):
            terms = list(result.reasoning_terms or [])
            if override_term not in terms:
                terms.append(override_term)
            for kw in matched:
                if kw not in terms:
                    terms.append(kw)
            result.reasoning_terms = terms
        elif isinstance(result, dict):
            terms = list(result.get("reasoning_terms", []))
            if override_term not in terms:
                terms.append(override_term)
            for kw in matched:
                if kw not in terms:
                    terms.append(kw)
            result["reasoning_terms"] = terms
