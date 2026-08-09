"""Evaluate CIM-Sight AI experiment results against a ground-truth anomaly log.

Computes, per experimental condition (and per difficulty):
  precision, recall, F1, hallucination rate, latency, evidence-attribution
  accuracy (EAA), and the difficulty-weighted document score.

Ground-truth CSV columns (one row per injected anomaly):
  doc_id, category, difficulty, page_number, section,
  original_text, modified_text, expected_detection, evidence

  category     : one of the 6 experiment categories (any casing)
  difficulty   : easy | medium | hard
  page_number  : page where the anomaly was injected

Difficulty scoring: easy=1, medium=2, hard=3 points when detected; 0 when missed.
Document score = points earned / points possible.

Matching: a detected finding matches a ground-truth anomaly when they share the
same doc_id, the same (normalized) category, and page numbers within +/-1.

Usage:
    python evaluate_results.py --ground-truth experiments/ground_truth.csv
    python evaluate_results.py --ground-truth experiments/ground_truth.csv \\
        --results-dir experiments/results
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


CATEGORY_ALIASES = {
    "math": "MATH ERRORS",
    "math/arithmetic errors": "MATH ERRORS",
    "arithmetic": "MATH ERRORS",
    "math errors": "MATH ERRORS",
    "margin": "MARGIN INCONSISTENCIES",
    "margin inconsistencies": "MARGIN INCONSISTENCIES",
    "projection": "AGGRESSIVE PROJECTIONS",
    "aggressive projections": "AGGRESSIVE PROJECTIONS",
    "aggressive projection": "AGGRESSIVE PROJECTIONS",
    "concentration": "CUSTOMER CONCENTRATION",
    "customer concentration": "CUSTOMER CONCENTRATION",
    "customer concentration risk": "CUSTOMER CONCENTRATION",
    "debt": "DEBT AND LIABILITY",
    "debt and liability": "DEBT AND LIABILITY",
    "debt and liability risk": "DEBT AND LIABILITY",
    "language": "MANAGEMENT LANGUAGE",
    "management language": "MANAGEMENT LANGUAGE",
    "management language tells": "MANAGEMENT LANGUAGE",
}

DIFFICULTY_POINTS = {"easy": 1, "medium": 2, "hard": 3}


def _norm_category(raw: str) -> str:
    key = (raw or "").strip().lower()
    if key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[key]
    for k, v in CATEGORY_ALIASES.items():
        if key.startswith(k):
            return v
    return (raw or "").strip().upper()


def _to_int(v):
    try:
        return int(float(v)) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def _load_ground_truth(path: Path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "doc_id": (r.get("doc_id") or "").strip(),
                "category": _norm_category(r.get("category", "")),
                "difficulty": (r.get("difficulty") or "medium").strip().lower(),
                "page_number": _to_int(r.get("page_number")),
                "section": (r.get("section") or "").strip(),
                "expected": (r.get("expected_detection") or r.get("expected") or "").strip(),
            })
    return rows


def _load_results(results_dir: Path):
    runs = []
    for p in sorted(results_dir.glob("*.json")):
        with open(p) as f:
            runs.append(json.load(f))
    return runs


def _match(finding, gt):
    """Same category AND page within +/-1 (page unknown => match on category)."""
    if _norm_category(finding.get("category", "")) != gt["category"]:
        return False
    fp = finding.get("page_number")
    gp = gt["page_number"]
    if fp is not None and gp is not None and abs(fp - gp) > 1:
        return False
    return True


def evaluate(gt_rows, runs):
    by_cond = defaultdict(list)
    for run in runs:
        by_cond[run["condition"]].append(run)

    report = {}
    for cond, cond_runs in by_cond.items():
        tp = fp = fn = 0
        halluc_removed = 0
        returned_findings = 0
        correct_citations = 0
        latency_ms = 0
        difficulty_score = 0
        difficulty_possible = 0
        per_diff = defaultdict(lambda: {"tp": 0, "fn": 0, "points": 0, "possible": 0})

        gt_by_doc = defaultdict(list)
        for g in gt_rows:
            gt_by_doc[g["doc_id"]].append(g)

        for run in cond_runs:
            doc_id = run.get("doc_id") or Path(run.get("source_file", "")).stem
            findings = run.get("findings", [])
            returned_findings += len(findings)
            m = run.get("metrics", {})
            halluc_removed += m.get("hallucinations_removed", 0)
            latency_ms += m.get("latency_ms", 0)

            doc_gt = list(gt_by_doc.get(doc_id, []))
            matched_gt = [False] * len(doc_gt)

            for f in findings:
                # EAA: a finding with a non-null page_number is "correctly cited".
                if f.get("page_number") is not None:
                    correct_citations += 1
                hit = None
                for gi, g in enumerate(doc_gt):
                    if matched_gt[gi]:
                        continue
                    if _match(f, g):
                        hit = gi
                        break
                if hit is not None:
                    matched_gt[hit] = True
                    tp += 1
                    g = doc_gt[hit]
                    pts = DIFFICULTY_POINTS.get(g["difficulty"], 2)
                    difficulty_score += pts
                    difficulty_possible += pts
                    per_diff[g["difficulty"]]["tp"] += 1
                    per_diff[g["difficulty"]]["points"] += pts
                else:
                    fp += 1

            for gi, g in enumerate(doc_gt):
                if not matched_gt[gi]:
                    fn += 1
                    pts = DIFFICULTY_POINTS.get(g["difficulty"], 2)
                    difficulty_possible += pts
                    per_diff[g["difficulty"]]["fn"] += 1
                    per_diff[g["difficulty"]]["possible"] += pts

        total_emitted = returned_findings + halluc_removed
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        halluc_rate = halluc_removed / total_emitted if total_emitted else 0.0
        eaa = correct_citations / returned_findings if returned_findings else 0.0
        doc_score = difficulty_score / difficulty_possible if difficulty_possible else 0.0

        report[cond] = {
            "runs": len(cond_runs),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "hallucination_rate": halluc_rate,
            "eaa": eaa,
            "latency_s": round(latency_ms / 1000, 1),
            "difficulty_score": difficulty_score,
            "difficulty_possible": difficulty_possible,
            "document_score": doc_score,
            "per_difficulty": {d: dict(v) for d, v in per_diff.items()},
        }
    return report


def main():
    ap = argparse.ArgumentParser(description="Evaluate experiment results vs ground truth.")
    ap.add_argument("--ground-truth", default="experiments/ground_truth.csv", type=Path)
    ap.add_argument("--results-dir", default="experiments/results", type=Path)
    args = ap.parse_args()

    if not args.ground_truth.exists():
        raise SystemExit(f"Ground-truth file not found: {args.ground_truth}")
    gt = _load_ground_truth(args.ground_truth)
    runs = _load_results(args.results_dir)
    if not runs:
        raise SystemExit(f"No result files in {args.results_dir}")

    report = evaluate(gt, runs)

    header = (f"{'CONDITION':<32} {'RUNS':>4} {'TP':>4} {'FP':>4} {'FN':>4} "
              f"{'PREC':>6} {'REC':>6} {'F1':>6} {'HALLUC':>7} {'EAA':>6} {'LAT_S':>6} {'DOCSC':>6}")
    print(header)
    print("-" * len(header))
    for cond in sorted(report):
        r = report[cond]
        print(f"{cond:<32} {r['runs']:>4} {r['tp']:>4} {r['fp']:>4} {r['fn']:>4} "
              f"{r['precision']:>6.3f} {r['recall']:>6.3f} {r['f1']:>6.3f} "
              f"{r['hallucination_rate']:>7.3f} {r['eaa']:>6.3f} "
              f"{r['latency_s']:>6.1f} {r['document_score']:>6.3f}")

    print("\nPer-detection-difficulty breakdown:")
    for cond in sorted(report):
        print(f"\n  {cond}")
        for d in ("easy", "medium", "hard"):
            pd = report[cond]["per_difficulty"].get(d, {"tp": 0, "fn": 0, "points": 0, "possible": 0})
            print(f"    {d:<7} detected={pd['tp']:>3} missed={pd['fn']:>3} "
                  f"score={pd['points']}/{pd['possible']}")

    print(f"\nGround truth: {len(gt)} anomalies. Results: {len(runs)} runs across "
          f"{len(report)} condition(s).")
    print("Use these per-condition means for your two-way ANOVA "
          "(parsing x prompting) on each metric.")


if __name__ == "__main__":
    main()
