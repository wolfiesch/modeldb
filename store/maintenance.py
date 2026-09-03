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
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from ingest.base import DB_PATH, connect
from store.spine import link_model


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

def relink_unlinked_benchmarks(conn: sqlite3.Connection) -> int:
    """Attempt to resolve and link benchmark_result rows whose model_id is NULL.

    Uses `store.spine.link_model` against each row's source_snapshot.source_id and
    eval_condition_json / raw_record_json metadata. Idempotent: rows that already
    have model_id are untouched, and unresolvable rows remain NULL.
    """
    rows = conn.execute(
        """
        SELECT br.id, ss.source_id, br.eval_condition_json
        FROM benchmark_result br
        JOIN source_snapshot ss ON ss.id = br.source_snapshot_id
        WHERE br.model_id IS NULL
        """
    ).fetchall()
    linked = 0
    for br_id, source_id, cond_json in rows:
        try:
            cond = json.loads(cond_json) if cond_json else {}
        except (ValueError, TypeError):
            continue
        source_model_id = (
            cond.get("source_model_id")
            or cond.get("model_name")
            or cond.get("slug")
            or ""
        )
        m_id = link_model(
            conn,
            source_id=source_id,
            source_model_id=source_model_id,
            parsed_fields=cond,
        )
        if m_id is not None:
            conn.execute(
                "UPDATE benchmark_result SET model_id = ? WHERE id = ?",
                (m_id, br_id),
            )
            linked += 1
    return linked


def run_maintenance(
    db_path: str | Path = DB_PATH,
    *,
    dedup: bool = True,
    relink: bool = False,
) -> dict[str, int]:
    """Run requested maintenance tasks against db_path and commit once at the end."""
    db_file = Path(db_path)
    result = {
        "benchmark_duplicates_removed": 0,
        "price_windows_capped": 0,
        "benchmarks_relinked": 0,
    }
    with closing(connect(db_file)) as conn, conn:
        if dedup:
            result["benchmark_duplicates_removed"] = dedup_benchmark_results(conn)
            result["price_windows_capped"] = cap_overlapping_price_windows(conn)
        if relink:
            result["benchmarks_relinked"] = relink_unlinked_benchmarks(conn)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Idempotent ModelDB maintenance tasks (safe to re-run)."
    )
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help="target SQLite database (default: db/modeldb.sqlite)")
    parser.add_argument("--dedup-facts", action="store_true",
                        help="remove exact duplicate benchmark_result rows and cap "
                             "superseded overlapping price_component windows")
    parser.add_argument("--relink-benchmarks", action="store_true",
                        help="attempt to resolve and link benchmark_result rows whose model_id is NULL")
    parser.add_argument("--all", action="store_true",
                        help="run all maintenance tasks (dedup-facts and relink-benchmarks)")
    args = parser.parse_args(argv)

    if not (args.dedup_facts or args.relink_benchmarks or args.all):
        parser.error("no task requested; pass --dedup-facts, --relink-benchmarks, or --all")

    dedup = args.dedup_facts or args.all
    relink = args.relink_benchmarks or args.all

    result = run_maintenance(args.db, dedup=dedup, relink=relink)
    parts = []
    if dedup:
        parts.append(
            f"removed {result['benchmark_duplicates_removed']} duplicate benchmark_result row(s), "
            f"capped {result['price_windows_capped']} overlapping price window(s)"
        )
    if relink:
        parts.append(f"relinked {result['benchmarks_relinked']} benchmark_result row(s)")
    summary = "; ".join(parts)
    print(f"maintenance: {summary}; database={args.db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
