# tests/test_dedup.py
from datetime import datetime, timedelta, timezone
from app.dedup import normalize_text, find_duplicate_clusters
from app.models import Ticket


def test_normalize_text():
    raw = "  Kolar Road MEIN   Phone +91 9876543210  "
    norm = normalize_text(raw)
    assert "<phone>" in norm
    assert "9876543210" not in norm
    assert norm == "kolar road mein phone <phone>"


def test_duplicate_clusters_near_duplicates_clustered():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    
    t1 = Ticket(
        id=1,
        batch_id="b1",
        ticket_hash="h1",
        sanitized_text="Kolar Road Mandakini drinking water pipeline phat gayi hai paani beh raha hai.",
        category="Pipe Burst",
        ward="Kolar Road",
        created_at=now
    )
    t2 = Ticket(
        id=2,
        batch_id="b1",
        ticket_hash="h2",
        sanitized_text="Kolar Road Mandakini drinking water pipe burst ho gaya hai paani beh raha hai.",
        category="Pipe Burst",
        ward="Kolar Road",
        created_at=now + timedelta(hours=2)
    )
    t3 = Ticket(
        id=3,
        batch_id="b1",
        ticket_hash="h3",
        sanitized_text="MP Nagar Zone 2 me streetlight band hai andhera hai.",
        category="Streetlight Outage",
        ward="MP Nagar",
        created_at=now + timedelta(hours=1)
    )

    cluster_map, links = find_duplicate_clusters([t1, t2, t3])

    # t1 and t2 should belong to the same cluster
    assert cluster_map[t1.id] == cluster_map[t2.id]
    # t3 should belong to a distinct cluster
    assert cluster_map[t3.id] != cluster_map[t1.id]


def test_duplicate_blocking_by_time_window():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    
    t1 = Ticket(
        id=1,
        batch_id="b1",
        ticket_hash="h1",
        sanitized_text="Kolar Road Mandakini me main drinking water pipeline phat gayi hai.",
        category="Pipe Burst",
        ward="Kolar Road",
        created_at=now
    )
    # Same incident reported 10 days later -> Should NOT cluster together (time window is <= 3 days)
    t2 = Ticket(
        id=2,
        batch_id="b1",
        ticket_hash="h2",
        sanitized_text="Kolar Road Mandakini me main drinking water pipeline phat gayi hai.",
        category="Pipe Burst",
        ward="Kolar Road",
        created_at=now + timedelta(days=10)
    )

    cluster_map, _ = find_duplicate_clusters([t1, t2])
    assert cluster_map[t1.id] != cluster_map[t2.id]
