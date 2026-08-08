"""Batch experiment runner for CIM-Sight AI v2.0 — 2x2 factorial design."""
from __future__ import annotations
import argparse, json, os, uuid
from datetime import datetime, timezone
from pathlib import Path
from cim_sight_pipeline import analyze_cim
from cim_sight_pipeline.config import get_preset, all_presets
from cim_sight_pipeline.metrics import ExperimentLogger, git_commit


def _iter_pdfs(target):
    if target.is_dir():
        yield from sorted(target.glob("*.pdf"))
    elif target.is_file() and target.suffix.lower() == ".pdf":
        yield target
    else:
        raise SystemExit(f"Not a PDF or directory: {target}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path)
    ap.add_argument("--presets", nargs="*", default=None)
    ap.add_argument("--api-key", default=None)
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
                run_id = str(uuid.uuid4())
                detail = {
                    "run_id": run_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "git_commit": git_commit(),
                    "doc_id": pdf.stem,
                    "source_file": str(pdf),
                    "condition": name,
                    "parser": cfg.parser,
                    "prompt_style": cfg.prompt_style,
                    "temperature": cfg.temperature,
                    "findings": results["findings"],
                    "metrics": results["metrics"],
                    "chunk_failures": results.get("chunk_failures", []),
                }
                out = args.results_dir / f"{name}__{pdf.stem}__{run_id[:8]}.json"
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
