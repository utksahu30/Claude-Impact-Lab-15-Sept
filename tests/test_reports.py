# tests/test_reports.py
from app.reports import sanitize_formula_injection


def test_sanitize_formula_injection():
    # Dangerous leading characters in spreadsheets: =, +, -, @
    assert sanitize_formula_injection("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert sanitize_formula_injection("+12345") == "'+12345"
    assert sanitize_formula_injection("-SUM(A1:A10)") == "'-SUM(A1:A10)"
    assert sanitize_formula_injection("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    
    # Safe text
    assert sanitize_formula_injection("Normal Text") == "Normal Text"
    assert sanitize_formula_injection(42) == "42"
