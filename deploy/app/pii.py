# app/pii.py
import re

# Defensive regex patterns for Indian phone and house numbers
PHONE_RE = re.compile(r"(?:\+?91[\s-]?)?[6-9]\d{9}\b")
HOUSE_NO_RE = re.compile(r"\b(?:house|makan|plot|flat)\s*(?:no\.?|number)?\s*[:\-]?\s*\d+[a-zA-Z]?\b", re.IGNORECASE)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """
    Performs defensive redaction on input complaint text.
    Returns:
        (sanitized_text, metadata_counts)
    Note: Counts and types are tracked; raw PII strings are NEVER stored or returned.
    """
    if not text:
        return "", {"phone": 0, "house_no": 0}

    counts = {"phone": 0, "house_no": 0}

    def _sub(pattern: re.Pattern, label: str, s: str) -> str:
        matches = pattern.findall(s)
        counts[label] += len(matches)
        return pattern.sub(f"[{label.upper()}_REDACTED]", s)

    sanitized = _sub(PHONE_RE, "phone", text)
    sanitized = _sub(HOUSE_NO_RE, "house_no", sanitized)

    return sanitized, counts
