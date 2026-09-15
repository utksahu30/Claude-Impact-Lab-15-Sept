# app/gazetteer.py
import json
from pathlib import Path
from typing import Optional
from rapidfuzz import process, fuzz

_candidate_gazetteers = [
    Path(__file__).resolve().parent.parent / "data" / "gazetteer.json",
    Path(__file__).resolve().parent / "data" / "gazetteer.json",
    Path("data") / "gazetteer.json",
    Path("/app/data") / "gazetteer.json"
]
GAZETTEER_PATH = next((p for p in _candidate_gazetteers if p.exists()), _candidate_gazetteers[0])

try:
    with open(GAZETTEER_PATH, "r", encoding="utf-8") as f:
        GAZETTEER: dict[str, list[str]] = json.load(f)
except Exception as e:
    print(f"[gazetteer] Warning: Failed to load gazetteer from {GAZETTEER_PATH}: {e}")
    GAZETTEER = {
        "MP Nagar": ["mp nagar", "maharana pratap nagar"],
        "Arera Colony": ["arera colony", "10 number market"],
        "Kolar Road": ["kolar", "kolar road"]
    }

# Build flat alias-to-canonical mapping
ALIAS_TO_WARD: dict[str, str] = {}
for canonical_ward, aliases in GAZETTEER.items():
    ALIAS_TO_WARD[canonical_ward.lower()] = canonical_ward
    for alias in aliases:
        ALIAS_TO_WARD[alias.lower()] = canonical_ward


def normalize_ward(raw: Optional[str], threshold: int = 80) -> Optional[str]:
    """
    Fuzzy matches an input ward/locality string against canonical Bhopal localities.
    Returns canonical ward name if similarity exceeds threshold, else None.
    """
    if not raw or not raw.strip():
        return None

    cleaned = raw.strip().lower()
    match = process.extractOne(cleaned, ALIAS_TO_WARD.keys(), scorer=fuzz.WRatio)
    if match and match[1] >= threshold:
        return ALIAS_TO_WARD[match[0]]
    return None


def extract_ward_from_text(text: str, threshold: int = 85) -> Optional[str]:
    """
    Scans complaint text for mentions of Bhopal wards/localities.
    Checks exact matches first, then falls back to fuzzy token matching.
    """
    if not text:
        return None

    lowered = text.lower()

    # Exact substring match check first (longest alias first for specificity)
    sorted_aliases = sorted(ALIAS_TO_WARD.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if len(alias) >= 3 and alias in lowered:
            return ALIAS_TO_WARD[alias]

    # Fuzzy extraction against word n-grams
    words = lowered.split()
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            ngram = " ".join(words[i:i+n])
            match = process.extractOne(ngram, ALIAS_TO_WARD.keys(), scorer=fuzz.token_sort_ratio)
            if match and match[1] >= threshold:
                return ALIAS_TO_WARD[match[0]]

    return None
