# tests/test_pii.py
from app.pii import redact


def test_phone_redaction():
    text1 = "Mera mobile number 9876543210 hai kripya call karein."
    sanitized1, counts1 = redact(text1)
    assert "[PHONE_REDACTED]" in sanitized1
    assert "9876543210" not in sanitized1
    assert counts1["phone"] == 1

    text2 = "Contact supervisor at +91 8123456789 or 7987654321 immediately."
    sanitized2, counts2 = redact(text2)
    assert counts2["phone"] == 2
    assert "8123456789" not in sanitized2
    assert "7987654321" not in sanitized2


def test_house_and_plot_redaction():
    text = "House no 42 Danish Kunj me sewer leak ho raha hai."
    sanitized, counts = redact(text)
    assert "[HOUSE_NO_REDACTED]" in sanitized
    assert "House no 42" not in sanitized
    assert counts["house_no"] == 1

    text_plot = "Plot 14B Shahpura me kachra dump ho raha hai."
    sanitized_plot, counts_plot = redact(text_plot)
    assert "[HOUSE_NO_REDACTED]" in sanitized_plot
    assert counts_plot["house_no"] == 1


def test_clean_text_no_redaction():
    text = "Sadak par pothole hai aur streetlight band hai."
    sanitized, counts = redact(text)
    assert sanitized == text
    assert counts["phone"] == 0
    assert counts["house_no"] == 0
