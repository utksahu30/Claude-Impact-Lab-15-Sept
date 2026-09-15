# app/fallback_classifier.py
from typing import Optional
from .schemas import ClassificationResult
from .gazetteer import extract_ward_from_text

# Comprehensive keyword lookup for offline triage (Hindi, Hinglish, English)
KEYWORD_MAP: list[tuple[list[str], str, str, str]] = [
    # (keywords, department, category, urgency)
    # 1. Critical Emergency Hazards
    (["fire", "aag", "cylinder blast", "dhamaka"], "Electricity", "Fire Hazard", "CRITICAL"),
    (["electrocution", "bijli ka jhatka", "current", "live wire", "exposed wire", "sparking"], "Electricity", "Hanging Live Wire", "CRITICAL"),
    (["gas leak", "building collapse", "girne wali"], "Roads & Infrastructure", "Emergency Hazard", "CRITICAL"),
    (["open manhole", "khula manhole", "manhole cover missing", "gutter khula", "deep open manhole"], "Roads & Infrastructure", "Open Manhole", "CRITICAL"),

    # 2. Public Health (Specific diseases & fogging must precede water/sanitation)
    (["fogging", "machhar", "mosquito", "dengue", "chikungunya", "malaria", "dawa chhidkaw"], "Public Health", "Mosquito Fogging", "MEDIUM"),

    # 3. Encroachment (Illegal construction / blocked footpath is actionable root cause)
    (["encroachment", "kabza", "illegal construction", "illegal shopkeepers", "footpath par kabza", "footpath block", "thela", "hawker"], "Encroachment", "Footpath Blocked", "LOW"),

    # 4. Drainage & Sewage (Specific sewage/drain/nallah terms)
    (["sewage", "gutter", "drain", "naali", "nallah", "nalah", "chamber block", "choked drain", "badboodar paani", "ganda badboodar"], "Drainage & Sewage", "Sewage Overflow", "HIGH"),

    # 5. Roads & Infrastructure (Waterlogging, potholes, broken roads)
    (["waterlogging", "water logging", "pothole", "gaddha", "road broken", "khadda", "tar road"], "Roads & Infrastructure", "Pothole", "MEDIUM"),

    # 6. Stray Animals (Use precise animal terms to avoid colliding with 'ho gaya')
    (["stray dog", "kutta", "kutto", "dog bites", "kutto ka aatank", "stray cattle", "gaay", " gay ", " bail ", "bandar", "awara"], "Stray Animals", "Dog Menace", "MEDIUM"),

    # 7. Electricity (Streetlights, transformers)
    (["transformer", "sparking transformer", "dhamaka transformer"], "Electricity", "Sparking Transformer", "HIGH"),
    (["streetlight", "street light", "andhera", "khamba light", "light band"], "Electricity", "Streetlight Outage", "MEDIUM"),

    # 8. Sanitation (Waste, dead animals)
    (["dead animal", "mara hua kutta", "mara janwar", "dead dog"], "Sanitation", "Dead Animal Removal", "HIGH"),
    (["kachra", "garbage", "dustbin", "safai", "dump", "gandagi", "kachrewala"], "Sanitation", "Waste Collection", "MEDIUM"),

    # 9. Water Supply (Drinking water, pipes, taps, tankers)
    (["pipe burst", "pipe leak", "paani bah raha", "pipeline leak", "pipeline"], "Water Supply", "Pipe Burst", "HIGH"),
    (["ganda paani", "contaminated water", "badboo paani", "peela aa raha", "peene yogya"], "Water Supply", "Contaminated Water", "HIGH"),
    (["water", "paani", "supply", "tonti", "nal", "boring", "tanker"], "Water Supply", "Supply Interruption", "MEDIUM"),

    # 10. General Road catch-all
    (["sadak", "road"], "Roads & Infrastructure", "Pothole", "MEDIUM"),
]


def fallback_classify(text: str, ward_hint: Optional[str] = None) -> ClassificationResult:
    """
    Deterministic, zero-network rule-based classifier.
    Serves as the resilient fallback when external AI is disabled or fails.
    Always returns a valid ClassificationResult with confidence 0.4 (or 0.0 if unassigned).
    """
    if not text or not text.strip():
        return ClassificationResult(
            department="UNASSIGNED",
            category="Empty Text",
            confidence_score=0.0,
            reasoning_terms=["empty_input"],
            ward=ward_hint or "UNKNOWN",
            urgency="LOW",
            ack_draft_en="Your complaint was received with insufficient details. An operator will contact you.",
            ack_draft_hi="आपकी शिकायत में पर्याप्त विवरण नहीं मिला। ऑपरेटर आपसे संपर्क करेगा।"
        )

    lowered = text.lower()
    detected_ward = ward_hint or extract_ward_from_text(text) or "UNKNOWN"

    # Search through keywords in order of priority
    for keywords, dept, cat, default_urgency in KEYWORD_MAP:
        matched = [kw for kw in keywords if kw in lowered]
        if matched:
            return ClassificationResult(
                department=dept,
                category=cat,
                confidence_score=0.40,
                reasoning_terms=matched,
                ward=detected_ward,
                urgency=default_urgency,  # will also pass through apply_safety_floor
                ack_draft_en=f"Your complaint regarding {cat.lower()} has been routed to the {dept} department.",
                ack_draft_hi=f"आपकी {cat} संबंधी शिकायत {dept} विभाग को भेज दी गई है।"
            )

    return ClassificationResult(
        department="UNASSIGNED",
        category="Unclassified",
        confidence_score=0.0,
        reasoning_terms=["fallback_no_match"],
        ward=detected_ward,
        urgency="MEDIUM",
        ack_draft_en="Your complaint has been logged and queued for manual operator review.",
        ack_draft_hi="आपकी शिकायत दर्ज कर ली गई है और ऑपरेटर समीक्षा के लिए कतारबद्ध है।"
    )
