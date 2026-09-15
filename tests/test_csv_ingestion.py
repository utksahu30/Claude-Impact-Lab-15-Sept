# tests/test_csv_ingestion.py
from app.csv_engine import decode_csv_bytes, inspect_csv_columns, compute_ticket_hash


def test_decode_csv_bytes_utf8():
    raw = "complaint,channel\nजल प्रदाय समस्या,Helpline".encode("utf-8")
    decoded, enc, was_lossy = decode_csv_bytes(raw)
    assert "जल प्रदाय समस्या" in decoded
    assert was_lossy is False
    assert "utf-8" in enc.lower()


def test_inspect_csv_columns():
    csv_text = "complaint_text,channel,ward\nPaani nahi aa raha,WhatsApp,Kolar\nRoad broken,Portal,MP Nagar\n"
    headers, samples, total = inspect_csv_columns(csv_text)
    assert headers == ["complaint_text", "channel", "ward"]
    assert total == 2
    assert len(samples) == 2
    assert samples[0]["channel"] == "WhatsApp"


def test_ticket_hash_idempotency():
    batch_id = "batch_20260915"
    text1 = "Kolar road pipe leak"
    text2 = "  Kolar ROAD   pipe LEAK  "
    
    hash1 = compute_ticket_hash(batch_id, text1)
    hash2 = compute_ticket_hash(batch_id, text2)
    assert hash1 == hash2
