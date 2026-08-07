from __future__ import annotations
import hashlib
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone


def compute_pdf_hash(pdf_path: str) -> str:
    """Phase 2 (#6): SHA-256 of the uploaded file for session caching."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


class ExperimentLogger:
    """Phase 6: research-grade logging. Every run is reproducible from its log."""

    def __init__(self, log_dir: str = "experiments/logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def log(self, config, result: dict, extra: dict = None) -> dict:
        rec = {
            "experiment_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit": git_commit(),
            "config": config.to_dict(),
            "metrics": result.get("metrics", {}),
            "session_hash": result.get("session_hash"),
            "findings_count": len(result.get("findings", [])),
            "rule_findings_count": len(result.get("rule_findings", [])),
            "chunk_failures": result.get("chunk_failures", []),
        }
        if extra:
            rec.update(extra)
        path = os.path.join(self.log_dir, rec["experiment_id"] + ".json")
        with open(path, "w") as f:
            json.dump(rec, f, indent=2)
        return rec
