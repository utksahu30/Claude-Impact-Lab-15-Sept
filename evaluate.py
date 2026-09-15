# evaluate.py
import json
from app.evaluation import run_held_out_benchmark


def main():
    print("=" * 65)
    print("  BHOPAL CIVIC TRIAGE ENGINE (PS-5) — HELD-OUT EVALUATION")
    print("=" * 65)
    print("Evaluating held-out test set (data/held_out_test.csv)...\n")

    results = run_held_out_benchmark()

    print(f"Total Test Cases (N):            {results['total_cases']}")
    print(f"Qwen 3.8 Max Routing Accuracy:   {results['llm_accuracy']}%")
    print(f"Deterministic Fallback Accuracy: {results['fallback_accuracy']}%")
    print(f"Duplicate Precision:             {results['duplicate_precision']}%")
    print(f"Duplicate Recall:                {results['duplicate_recall']}%")
    print("-" * 65)

    print("\nCase-by-case Breakdown:")
    print(f"{'#':<3} | {'Expected Dept':<22} | {'Predicted Dept':<22} | {'Match?':<6} | {'Urgency':<8}")
    print("-" * 75)
    for c in results["cases"]:
        match_str = "YES" if c["is_match"] else "NO"
        print(f"{c['id']:<3} | {c['expected_dept']:<22} | {c['predicted_dept']:<22} | {match_str:<6} | {c['predicted_urgency']:<8}")

    # Persist results
    with open("evaluation_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print("\n[OK] Results saved to evaluation_results.json")


if __name__ == "__main__":
    main()
