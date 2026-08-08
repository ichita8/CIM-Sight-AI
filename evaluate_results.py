"""Evaluate CIM-Sight AI experiment results against a ground-truth anomaly log."""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from pathlib import Path

CATEGORY_ALIASES = {
    "math": "MATH ERRORS", "math/arithmetic errors": "MATH ERRORS",
    "arithmetic": "MATH ERRORS", "math errors": "MATH ERRORS",
    "margin": "MARGIN INCONSISTENCIES", "margin inconsistencies": "MARGIN INCONSISTENCIES",
    "projection": "AGGRESSIVE PROJECTIONS", "aggressive projections": "AGGRESSIVE PROJECTIONS",
    "concentration": "CUSTOMER CONCENTRATION", "customer concentration": "CUSTOMER CONCENTRATION",
    "customer concentration risk": "CUSTOMER CONCENTRATION",
    "debt": "DEBT AND LIABILITY", "debt and liability": "DEBT AND LIABILITY",
    "debt and liability risk": "DEBT AND LIABILITY",
    "language": "MANAGEMENT LANGUAGE", "management language": "MANAGEMENT LANGUAGE",
    "management language tells": "MANAGEMENT LANGUAGE",
}
DIFFICULTY_POINTS = {"easy": 1, "medium": 2, "hard": 3}


def _norm_category(raw):
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


def _load_ground_truth(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "doc_id": (r.get("doc_id") or "").strip(),
                "category": _norm_category(r.get("category", "")),
                "difficulty": (r.get("difficulty") or "medium").strip().lower(),
                "page_number": _to_int(r.get("page_number")),
            })
    return rows


def _match(finding, gt):
    if _norm_category(finding.get("category", "")) != gt["category"]:
        return False
    fp, gp = finding.get("page_number"), gt["page_number"]
    if fp is not None and gp is not None and abs(fp - gp) > 1:
        return False
    return True


def evaluate(gt_rows, runs):
    by_cond = defaultdict(list)
    for run in runs:
        by_cond[run["condition"]].append(run)
    report = {}
    for cond, cond_runs in by_cond.items():
        tp = fp = fn = halluc = returned = cited = latency = 0
        dscore = dpossible = 0
        per_diff = defaultdict(lambda: {"tp": 0, "fn": 0, "points": 0, "possible": 0})
        gt_by_doc = defaultdict(list)
        for g in gt_rows:
            gt_by_doc[g["doc_id"]].append(g)
        for run in cond_runs:
            doc_id = run.get("doc_id") or Path(run.get("source_file", "")).stem
            findings = run.get("findings", [])
            returned += len(findings)
            m = run.get("metrics", {})
            halluc += m.get("hallucinations_removed", 0)
            latency += m.get("latency_ms", 0)
            doc_gt = list(gt_by_doc.get(doc_id, []))
            matched = [False] * len(doc_gt)
            for f in findings:
                if f.get("page_number") is not None:
                    cited += 1
                hit = next((gi for gi, g in enumerate(doc_gt)
                            if not matched[gi] and _match(f, g)), None)
                if hit is not None:
                    matched[hit] = True
                    tp += 1
                    g = doc_gt[hit]
                    pts = DIFFICULTY_POINTS.get(g["difficulty"], 2)
                    dscore += pts; dpossible += pts
                    per_diff[g["difficulty"]]["tp"] += 1
                    per_diff[g["difficulty"]]["points"] += pts
                else:
                    fp += 1
            for gi, g in enumerate(doc_gt):
                if not matched[gi]:
                    fn += 1
                    pts = DIFFICULTY_POINTS.get(g["difficulty"], 2)
                    dpossible += pts
                    per_diff[g["difficulty"]]["fn"] += 1
                    per_diff[g["difficulty"]]["possible"] += pts
        emitted = returned + halluc
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        report[cond] = {
            "runs": len(cond_runs), "tp": tp, "fp": fp, "fn": fn,
            "precision": prec, "recall": rec, "f1": f1,
            "hallucination_rate": halluc / emitted if emitted else 0.0,
            "eaa": cited / returned if returned else 0.0,
            "latency_s": round(latency / 1000, 1),
            "document_score": dscore / dpossible if dpossible else 0.0,
            "per_difficulty": {d: dict(v) for d, v in per_diff.items()},
        }
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ground-truth", default="experiments/ground_truth.csv", type=Path)
    ap.add_argument("--results-dir", default="experiments/results", type=Path)
    args = ap.parse_args()
    if not args.ground_truth.exists():
        raise SystemExit(f"Ground-truth file not found: {args.ground_truth}")
    gt = _load_ground_truth(args.ground_truth)
    runs = [json.load(open(p)) for p in sorted(args.results_dir.glob("*.json"))]
    if not runs:
        raise SystemExit(f"No result files in {args.results_dir}")
    report = evaluate(gt, runs)
    header = (f"{'CONDITION':<32} {'RUNS':>4} {'TP':>4} {'FP':>4} {'FN':>4} "
              f"{'PREC':>6} {'REC':>6} {'F1':>6} {'HALLUC':>7} {'EAA':>6} {'LAT_S':>6} {'DOCSC':>6}")
    print(header); print("-" * len(header))
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
