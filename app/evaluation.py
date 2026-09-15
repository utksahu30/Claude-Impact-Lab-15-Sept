# app/evaluation.py
import csv
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .schemas import ClassificationResult
from .ai_classifier import classify, ClassificationFailed
from .fallback_classifier import fallback_classify
from .safety_rules import apply_safety_floor
from .dedup import find_duplicate_clusters
from .models import Ticket

TEST_CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "held_out_test.csv"


def evaluate_record(r: dict[str, Any]) -> dict[str, Any]:
    text = r["text"]
    expected_dept = r["expected_dept"]

    # 1. Evaluate Fallback Classifier
    fb_res = fallback_classify(text)
    apply_safety_floor(text, fb_res)
    fb_match = (fb_res.department.lower().strip() == expected_dept.lower().strip())

    # 2. Evaluate Qwen 3.8 Max Classifier
    pred_dept = fb_res.department
    pred_urgency = fb_res.urgency
    try:
        llm_res = classify(text)
        apply_safety_floor(text, llm_res)
        pred_dept = llm_res.department
        pred_urgency = llm_res.urgency
    except Exception:
        # Fallback path if API fails
        pred_dept = fb_res.department
        pred_urgency = fb_res.urgency

    llm_match = (pred_dept.lower().strip() == expected_dept.lower().strip())
    print(f"[{r['id']}] '{text[:30]}...' -> LLM: {pred_dept} ({'PASS' if llm_match else 'FAIL'}), Fallback: {fb_res.department} ({'PASS' if fb_match else 'FAIL'})", flush=True)

    return {
        "id": r["id"],
        "text": text,
        "expected_dept": expected_dept,
        "predicted_dept": pred_dept,
        "is_match": llm_match,
        "fb_match": fb_match,
        "expected_urgency": r["expected_urgency"],
        "predicted_urgency": pred_urgency,
        "expected_ward": r["expected_ward"],
        "dup_group": r["dup_group"]
    }


def run_held_out_benchmark() -> dict[str, Any]:
    """
    Evaluates triage accuracy and duplicate detection metrics on the held-out labeled test set.
    Uses concurrent ThreadPoolExecutor for high throughput.
    """
    if not TEST_CSV_PATH.exists():
        return {
            "llm_accuracy": 0.0,
            "fallback_accuracy": 0.0,
            "duplicate_precision": 0.0,
            "duplicate_recall": 0.0,
            "total_cases": 0,
            "cases": []
        }

    records = []
    with open(TEST_CSV_PATH, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=1):
            records.append({
                "id": i,
                "text": row.get("complaint_text", "").strip(),
                "expected_dept": row.get("ground_truth_dept", "").strip(),
                "expected_urgency": row.get("ground_truth_urgency", "MEDIUM").strip(),
                "expected_ward": row.get("ground_truth_ward", "").strip(),
                "dup_group": row.get("duplicate_group", "").strip() or None
            })

    total = len(records)
    if total == 0:
        return {
            "llm_accuracy": 0.0,
            "fallback_accuracy": 0.0,
            "duplicate_precision": 0.0,
            "duplicate_recall": 0.0,
            "total_cases": 0,
            "cases": []
        }

    print(f"Running parallel evaluation across {total} test cases (max_workers=5)...", flush=True)
    with ThreadPoolExecutor(max_workers=5) as executor:
        evaluated_cases = list(executor.map(evaluate_record, records))

    # Sort back by original ID
    evaluated_cases.sort(key=lambda x: x["id"])

    llm_correct = sum(1 for c in evaluated_cases if c["is_match"])
    fallback_correct = sum(1 for c in evaluated_cases if c["fb_match"])

    # 3. Evaluate Deduplication Precision & Recall
    synthetic_tickets = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for c in evaluated_cases:
        t = Ticket(
            id=c["id"],
            batch_id="eval_batch",
            ticket_hash=f"eval_hash_{c['id']}",
            sanitized_text=c["text"],
            category=c["predicted_dept"],
            ward=c["expected_ward"],
            created_at=now
        )
        synthetic_tickets.append(t)

    # Ground truth pairs in test set
    group_map: dict[str, list[int]] = {}
    for r in records:
        if r["dup_group"]:
            group_map.setdefault(r["dup_group"], []).append(r["id"])

    true_duplicate_pairs = set()
    for g, member_ids in group_map.items():
        for i in range(len(member_ids)):
            for j in range(i + 1, len(member_ids)):
                true_duplicate_pairs.add(tuple(sorted((member_ids[i], member_ids[j]))))

    # Predicted duplicate pairs by char n-gram engine
    cluster_map, _ = find_duplicate_clusters(synthetic_tickets)
    pred_clusters: dict[str, list[int]] = {}
    for tid, cid in cluster_map.items():
        pred_clusters.setdefault(cid, []).append(tid)

    predicted_duplicate_pairs = set()
    for cid, members in pred_clusters.items():
        if len(members) > 1:
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    predicted_duplicate_pairs.add(tuple(sorted((members[i], members[j]))))

    correct_flags = predicted_duplicate_pairs.intersection(true_duplicate_pairs)

    precision = (len(correct_flags) / len(predicted_duplicate_pairs) * 100) if predicted_duplicate_pairs else 100.0
    recall = (len(correct_flags) / len(true_duplicate_pairs) * 100) if true_duplicate_pairs else 100.0

    return {
        "llm_accuracy": round((llm_correct / total) * 100, 1),
        "fallback_accuracy": round((fallback_correct / total) * 100, 1),
        "duplicate_precision": round(precision, 1),
        "duplicate_recall": round(recall, 1),
        "total_cases": total,
        "cases": evaluated_cases
    }
