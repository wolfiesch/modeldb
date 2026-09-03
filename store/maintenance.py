"""Idempotent maintenance for accumulated fact-table drift.

Usage:
    python3 -m store.maintenance --dedup-facts [--db PATH]

Tasks are safe to re-run: each one is a no-op once the database is clean, and
each one only touches the exact drift it targets. Nothing here rewrites
provenance, scores, or dates; superseded price rows keep their identity and
only get their `valid_to` bounded by the newer observation that overlaps them.
"""
from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from ingest.base import DB_PATH, connect


def dedup_benchmark_results(conn: sqlite3.Connection) -> int:
    """Delete exact duplicate benchmark_result rows, keeping the first seen.

    Duplicate means identical (model_id, benchmark_id, score,
    eval_condition_json, source_snapshot_id) — the fan-out signature of
    promoters re-reading historical snapshots. The lowest id (first-seen)
    survives so provenance stays stable across runs.
    """
    before = int(conn.execute("SELECT COUNT(*) FROM benchmark_result").fetchone()[0])
    conn.execute(
        """
        DELETE FROM benchmark_result
        WHERE id NOT IN (
            SELECT MIN(id) FROM benchmark_result
            GROUP BY model_id, benchmark_id, score, eval_condition_json, source_snapshot_id
        )
        """
    )
    after = int(conn.execute("SELECT COUNT(*) FROM benchmark_result").fetchone()[0])
    return before - after


def cap_overlapping_price_windows(conn: sqlite3.Connection) -> int:
    """Bound superseded price rows with valid_to when a newer observation overlaps.

    Within each (model_id, provider_surface_id, component) timeline ordered by
    valid_from, an older row whose valid_to is NULL or extends past the next
    row's valid_from gets capped to exactly that valid_from. Rows that already
    abut or precede their successor are untouched, so the pass is idempotent.
    """
    rows = conn.execute(
        """
        SELECT id, model_id, provider_surface_id, component, valid_from, valid_to
        FROM price_component
        ORDER BY model_id, provider_surface_id, component, valid_from, id
        """
    ).fetchall()

    groups: dict[tuple, list[tuple]] = {}
    for row in rows:
        groups.setdefault((row[1], row[2], row[3]), []).append(row)

    capped = 0
    for group in groups.values():
        for older, newer in zip(group, group[1:]):
            older_id, older_to = older[0], older[5]
            newer_from = newer[4]
            if newer_from is None:
                continue
            if older_to is None or older_to > newer_from:
                cursor = conn.execute(
                    """
                    UPDATE price_component SET valid_to = ?
                    WHERE id = ? AND (valid_to IS NULL OR valid_to > ?)
                    """,
                    (newer_from, older_id, newer_from),
                )
                capped += cursor.rowcount
    return capped


def run_maintenance(db_path: str | Path = DB_PATH) -> dict[str, int]:
    """Run every maintenance task against db_path and commit once at the end."""
    db_file = Path(db_path)
    with closing(connect(db_file)) as conn, conn:
        benchmark_duplicates_removed = dedup_benchmark_results(conn)
        price_windows_capped = cap_overlapping_price_windows(conn)
    return {
        "benchmark_duplicates_removed": benchmark_duplicates_removed,
        "price_windows_capped": price_windows_capped,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent ModelDB maintenance tasks (safe to re-run)."
    )
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="target SQLite database (default: db/modeldb.sqlite)")
    parser.add_argument("--dedup-facts", action="store_true",
                        help="remove exact duplicate benchmark_result rows and cap "
                             "superseded overlapping price_component windows")
    args = parser.parse_args(argv)

    if not args.dedup_facts:
        parser.error("no task requested; pass --dedup-facts")

    result = run_maintenance(args.db)
    print(
        f"maintenance: removed {result['benchmark_duplicates_removed']} duplicate "
        f"benchmark_result row(s), capped {result['price_windows_capped']} "
        f"overlapping price window(s); database={args.db}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
