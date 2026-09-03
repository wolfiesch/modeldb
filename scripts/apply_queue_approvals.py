from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resolve.resolver import accept_queue_batch, drain_accepted_queue


DEFAULT_DB_PATH = Path("db/modeldb.sqlite")
DEFAULT_BACKUP_DIR = Path("db/backups")
TIMESTAMP_HELPER = Path.home() / ".omp/agent/bin/omp-timestamp"


def apply_queue_approvals(
    approvals_path: Path,
    *,
    db_path: Path = DEFAULT_DB_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    run_pipeline: bool = True,
    repo_root: Path | None = None,
    backup_label: str | None = None,
) -> dict[str, Any]:
    """Apply reviewed queue approvals through the guarded accept/drain sequence."""

    repo_root = repo_root or Path.cwd()
    approvals = _load_approvals(approvals_path)
    backup_path = _backup_database(db_path, backup_dir, backup_label=backup_label)

    conn = sqlite3.connect(db_path)
    try:
        accept_dry_run = accept_queue_batch(conn, approvals, dry_run=True)
        accept_summary = accept_queue_batch(conn, approvals)
        drain_dry_run = drain_accepted_queue(conn, dry_run=True)
        drain_summary = drain_accepted_queue(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    pipeline_summary: dict[str, Any]
    if run_pipeline:
        result = subprocess.run(
            [sys.executable, "-m", "store.pipeline", "--no-fetch"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        pipeline_summary = {"run": True, "stdout": result.stdout}
    else:
        pipeline_summary = {"run": False, "reason": "disabled"}

    return {
        "approvals_path": str(approvals_path),
        "backup_path": str(backup_path),
        "approval_count": len(approvals),
        "accept_dry_run": accept_dry_run,
        "accept": accept_summary,
        "drain_dry_run": drain_dry_run,
        "drain": drain_summary,
        "pipeline": pipeline_summary,
    }


def _load_approvals(path: Path) -> list[dict[str, Any]]:
    loaded = json.loads(path.read_text())
    if not isinstance(loaded, list):
        raise ValueError("approvals file must contain a JSON array")
    for item in loaded:
        if not isinstance(item, dict):
            raise ValueError("each approval must be a JSON object")
    return loaded


def _backup_database(db_path: Path, backup_dir: Path, *, backup_label: str | None = None) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    label = backup_label or _backup_label_from_timestamp()
    backup_path = _next_backup_path(backup_dir, label)
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path

def _next_backup_path(backup_dir: Path, label: str) -> Path:
    base = backup_dir / f"modeldb-before-queue-approvals-{label}.sqlite"
    if not base.exists():
        return base
    suffix = 2
    while True:
        candidate = backup_dir / f"modeldb-before-queue-approvals-{label}-{suffix}.sqlite"
        if not candidate.exists():
            return candidate
        suffix += 1


def _backup_label_from_timestamp() -> str:
    if TIMESTAMP_HELPER.exists():
        timestamp = subprocess.check_output([str(TIMESTAMP_HELPER)], text=True).strip()
    else:
        timestamp = datetime.now(timezone.utc).isoformat()
    sanitized = "".join(char if char.isalnum() else "-" for char in timestamp)
    return "-".join(part for part in sanitized.split("-") if part)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply reviewed entity-resolution queue approvals safely.")
    parser.add_argument("approvals_json", type=Path, help="Reviewed JSON array of {queue_id, candidate_model_id} approvals.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path.")
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR, help="Directory for pre-mutation SQLite backups.")
    parser.add_argument("--skip-pipeline", action="store_true", help="Skip python -m store.pipeline --no-fetch after drain.")
    args = parser.parse_args(argv)

    summary = apply_queue_approvals(
        args.approvals_json,
        db_path=args.db,
        backup_dir=args.backup_dir,
        run_pipeline=not args.skip_pipeline,
        repo_root=Path.cwd(),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
