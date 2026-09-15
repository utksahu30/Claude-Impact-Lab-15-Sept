# tests/test_safety_rules.py
from app.safety_rules import contains_safety_keyword, apply_safety_floor
from app.schemas import ClassificationResult


def test_contains_safety_keyword():
    assert contains_safety_keyword("Transformer me aag lag gayi hai") is True
    assert contains_safety_keyword("Live wire latak raha hai electrocution ho sakta hai") is True
    assert contains_safety_keyword("Sadak par open manhole hai bina dhakkan ke") is True
    assert contains_safety_keyword("Normal water supply interruption hai") is False


def test_apply_safety_floor_bumps_to_critical():
    result = ClassificationResult(
        department="Electricity",
        category="Streetlight Outage",
        confidence_score=0.9,
        reasoning_terms=["light"],
        ward="MP Nagar",
        urgency="MEDIUM",
        ack_draft_en="Draft ack"
    )

    emergency_text = "Live wire tut gaya hai bijli ka jhatka lagne ka khatra hai"
    apply_safety_floor(emergency_text, result)

    assert result.urgency == "CRITICAL"
    assert "safety_rule_override" in result.reasoning_terms


def test_apply_safety_floor_leaves_non_hazard_unchanged():
    result = ClassificationResult(
        department="Water Supply",
        category="Supply Interruption",
        confidence_score=0.85,
        reasoning_terms=["water"],
        ward="Kolar Road",
        urgency="MEDIUM",
        ack_draft_en="Draft ack"
    )

    normal_text = "Subah se paani nahi aa raha hai kripya jaldi bhejiye."
    apply_safety_floor(normal_text, result)

    assert result.urgency == "MEDIUM"
    assert "safety_rule_override" not in result.reasoning_terms
