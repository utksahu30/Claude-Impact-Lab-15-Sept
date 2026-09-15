# app/dedup.py
import re
import unicodedata
from typing import Any, Sequence
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .config import settings
from .models import DuplicateLink


def normalize_text(s: str) -> str:
    """
    Normalizes text for robust char n-gram similarity:
    - NFKC unicode normalization
    - Whitespace collapsing
    - Lowercasing
    - Masking phone numbers so random numbers don't affect similarity
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"(?:\+?91[\s-]?)?[6-9]\d{9}", "<phone>", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


class UnionFind:
    """Disjoint-set union data structure for connected-component duplicate clusters."""
    def __init__(self, ids: Sequence[int]):
        self.parent = {i: i for i in ids}

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # Path compression
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def find_duplicate_clusters(tickets: list[Any]) -> tuple[dict[int, str], list[DuplicateLink]]:
    """
    Identifies duplicate incident clusters across tickets.

    Blocking Rule (Gap #2 fix):
    - Blocking is by TIME WINDOW ONLY (within 3 days).
    - Category and ward agreement only nudge similarity (+0.03 bonus each);
      they NEVER gate a comparison, allowing misclassified duplicates to still be linked.

    Returns:
      (ticket_to_cluster_map, list_of_duplicate_links)
    """
    if not tickets:
        return {}, []

    valid_tickets = [t for t in tickets if t.id is not None]
    if len(valid_tickets) < 2:
        return {t.id: str(t.id) for t in valid_tickets}, []

    uf = UnionFind([t.id for t in valid_tickets])
    duplicate_links: list[DuplicateLink] = []

    # Prepare normalized texts
    texts = [normalize_text(getattr(t, "sanitized_text", "") or getattr(t, "raw_text", "")) for t in valid_tickets]

    # Character n-grams (2-4): handles transliteration, spelling variations in Hindi/Hinglish
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1)
    try:
        matrix = vectorizer.fit_transform(texts)
        sim_matrix = cosine_similarity(matrix)
    except Exception:
        # Fallback if vocabulary is completely empty
        return {t.id: str(t.id) for t in valid_tickets}, []

    n = len(valid_tickets)
    for i in range(n):
        for j in range(i + 1, n):
            t1, t2 = valid_tickets[i], valid_tickets[j]

            # Hard filter: Incident reports must be within 3 days
            within_window = abs((t1.created_at - t2.created_at).total_seconds()) <= (3 * 86400)
            if not within_window:
                continue

            base_score = float(sim_matrix[i, j])
            score = base_score

            # Soft bonuses (never gates)
            if t1.category and t2.category and t1.category == t2.category:
                score += 0.03
            if t1.ward and t2.ward and t1.ward == t2.ward and t1.ward != "UNKNOWN":
                score += 0.03

            if score >= settings.duplicate_similarity_threshold:
                uf.union(t1.id, t2.id)

    # Build cluster mapping
    cluster_map: dict[int, str] = {t.id: f"cluster-{uf.find(t.id)}" for t in valid_tickets}

    # Record duplicate links for any ticket that belongs to a multi-member cluster
    cluster_counts: dict[str, list[int]] = {}
    for tid, cid in cluster_map.items():
        cluster_counts.setdefault(cid, []).append(tid)

    for cid, members in cluster_counts.items():
        if len(members) > 1:
            for tid in members:
                duplicate_links.append(
                    DuplicateLink(
                        ticket_id=tid,
                        duplicate_of_cluster=cid,
                        similarity_score=settings.duplicate_similarity_threshold,
                        method="tfidf_char_ngram",
                        confirmed_by_operator=False
                    )
                )

    return cluster_map, duplicate_links
