#!/usr/bin/env python3
"""Collect bounded visible-output TPS samples from the local OMP speedtest helper."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_CONFIG = REPO_ROOT / "scripts" / "omp_tps_models.json"
DEFAULT_PROMPT = "Output 180 comma-separated integers starting at 1. No explanation."
SPEEDTEST = Path(os.environ.get("OMP_SPEEDTEST_SCRIPT", Path.home() / ".omp/agent/skills/omp-model-speedtest/scripts/omp_speedtest.py"))
if not SPEEDTEST.exists():
    SPEEDTEST = REPO_ROOT / "scripts" / "omp_speedtest.py"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    models = load_models(args.config)

    if args.dry_run:
        print(json.dumps({"models": models}, indent=2))
        return 0

    if os.environ.get("OMP_TPS_ALLOW_PAID") != "1":
        print("Set OMP_TPS_ALLOW_PAID=1 to run metered OMP benchmark calls.", file=sys.stderr)
        return 1

    ensure_source_registered()

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = REPO_ROOT / ".perf" / "omp-tps" / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    command = [
        "python3",
        str(SPEEDTEST),
        "--visible",
        "--runs",
        str(args.runs),
        "--interleave",
        "--timeout",
        str(args.timeout),
        "--prompt",
        args.prompt,
        "--json",
        *[model["ompSelector"] for model in models],
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        error_payload = {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "command": command,
        }
        (artifact_dir / "error.json").write_text(json.dumps(error_payload, indent=2), encoding="utf-8")
        return completed.returncode

    speedtest = json.loads(completed.stdout)
    artifact_path = f".perf/omp-tps/{run_id}/payload.json"
    payload = {
        "runId": run_id,
        "createdAt": datetime.now(UTC).isoformat(),
        "sourceHash": source_hash(),
        "buildMode": "local-omp-cli-visible",
        "scenario": "visible-output-counting-prompt",
        "runs": args.runs,
        "timeoutSeconds": args.timeout,
        "prompt": args.prompt,
        "artifactPath": artifact_path,
        "models": models,
        "speedtest": speedtest,
    }
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    (artifact_dir / "payload.json").write_bytes(raw)

    from ingest.base import connect
    from ingest.sources.omp_speedtest import OMPSpeedtestParser
    from store.omp_speedtest import promote_omp_speedtest

    parser = OMPSpeedtestParser()
    with connect() as conn:
        snapshot_id = parser.snapshot(conn, f"file://{artifact_path}", raw, {})
        parser.store_records(conn, snapshot_id, parser.parse(raw, snapshot_id))
        summary = promote_omp_speedtest(conn)
        conn.commit()
    print(json.dumps(summary, sort_keys=True))
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect local OMP visible-output TPS samples.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def load_models(path: Path) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"{path} must contain a JSON array")
    required = {"key", "label", "canonicalSlug", "ompSelector", "providerLabel"}
    for row in rows:
        if not isinstance(row, dict) or not required.issubset(row):
            raise ValueError(f"{path} contains an invalid model row")
    return rows


def ensure_source_registered() -> None:
    from ingest.base import connect

    with connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO source
              (id, name, base_url, ingestion_class, auth_type, update_cadence, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "omp_speedtest",
                "OMP local speedtest",
                "local:~/.omp/agent/skills/omp-model-speedtest/scripts/omp_speedtest.py",
                "A",
                "local_auth",
                "daily",
                "Local bounded OMP speedtest JSON. Stores visible-output TPS from subscription or configured provider routes. Billing-sensitive; runner requires OMP_TPS_ALLOW_PAID=1.",
            ),
        )
        conn.commit()


def source_hash() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
