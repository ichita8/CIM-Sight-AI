"""Batch experiment runner for CIM-Sight AI v2.0 — 2x2 factorial design.

Runs the four experimental conditions against a PDF (or folder of PDFs),
logs every run, and writes a detailed per-run results file for evaluation
against the ground-truth anomaly log via evaluate_results.py.

Conditions (all at temperature = 0.0):
    baseline_standard_generic   — Standard text + Generic prompt
    prompt_only_standard_cim     — Standard text + CIM-Sight prompt
    parser_only_pymupdf_generic  — PyMuPDF markdown + Generic prompt
    full_cim_sight               — PyMuPDF markdown + CIM-Sight prompt

Usage:
    python run_experiment.py path/to/modified_cims/
    python run_experiment.py path/to/deal.pdf --presets full_cim_sight baseline_standard_generic
    python run_experiment.py path/to/deal.pdf --api-key csk-...
"""
from __future__ import annotations
import argparse
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cim_sight_pipeline import analyze_cim
from cim_sight_pipeline.config import get_preset, all_presets
from cim_sight_pipeline.metrics import ExperimentLogger, git_commit


def _iter_pdfs(target: Path):
    if target.is_dir():
        yield from sorted(target.glob("*.pdf"))
    elif target.is_file() and target.suffix.lower() == ".pdf":
        yield target
    else:
        raise SystemExit(f"Not a PDF or directory: {target}")


def _doc_id(pdf: Path) -> str:
    return pdf.stem


def main():
    ap = argparse.ArgumentParser(description="Run CIM-Sight AI experiments (2x2 factorial).")
    ap.add_argument("target", type=Path, help="PDF file or directory of PDFs")
    ap.add_argument("--presets", nargs="*", default=None,
                    help="Condition names to run (default: all four)")
    ap.add_argument("--api-key", default=None,
                    help="Cerebras API key (defaults to env CEREBRAS_API_KEY)")
    ap.add_argument("--results-dir", default="experiments/results", type=Path)
    args = ap.parse_args()

    if args.api_key:
        os.environ["CEREBRAS_API_KEY"] = args.api_key
    if not os.environ.get("CEREBRAS_API_KEY"):
        raise SystemExit("Set CEREBRAS_API_KEY env var or pass --api-key.")

    preset_names = args.presets or all_presets()
    pdfs = list(_iter_pdfs(args.target))
    if not pdfs:
        raise SystemExit("No PDF files found.")

    args.results_dir.mkdir(parents=True, exist_ok=True)
    logger = ExperimentLogger()
    print(f"Running {len(preset_names)} condition(s) across {len(pdfs)} PDF(s)\n")

    for pdf in pdfs:
        for name in preset_names:
            cfg = get_preset(name)
            print(f"  -> {pdf.name} . {name} ...", end=" ", flush=True)
            try:
                results = analyze_cim(pdf, cfg)
                logger.log(cfg, results, extra={"source_file": str(pdf)})

                # Detailed results file for evaluation against ground truth.
                run_id = str(uuid.uuid4())
                detail = {
                    "run_id": run_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "git_commit": git_commit(),
                    "doc_id": _doc_id(pdf),
                    "source_file": str(pdf),
                    "condition": name,
                    "parser": cfg.parser,
                    "prompt_style": cfg.prompt_style,
                    "temperature": cfg.temperature,
                    "findings": results["findings"],
                    "metrics": results["metrics"],
                    "chunk_failures": results.get("chunk_failures", []),
                }
                out = args.results_dir / f"{name}__{_doc_id(pdf)}__{run_id[:8]}.json"
                with open(out, "w") as f:
                    json.dump(detail, f, indent=2)

                m = results["metrics"]
                print(f"flags={len(results['findings'])} "
                      f"halluc={m.get('hallucinations_removed', 0)} "
                      f"retries={m.get('retries', 0)} "
                      f"latency={m.get('latency_ms', 0)}ms")
            except Exception as exc:
                print(f"FAILED: {exc}")

    print(f"\nDone. Detailed results in {args.results_dir}/.\n"
          f"Run: python evaluate_results.py --ground-truth experiments/ground_truth.csv")


if __name__ == "__main__":
    main()
