"""Preserve repeated price observations without duplicating active price facts."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from ingest.base import DB_PATH, connect


_OBSERVATION_DDL = """
CREATE TABLE IF NOT EXISTS price_component_observation (
  price_component_id INTEGER NOT NULL REFERENCES price_component(id) ON DELETE CASCADE,
  source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshot(id),
  PRIMARY KEY (price_component_id, source_snapshot_id)
)
"""


def ensure_price_observation_table(conn: sqlite3.Connection) -> None:
    """Create the provenance sidecar used when duplicate facts are coalesced."""
    conn.execute(_OBSERVATION_DDL)


def _intervals_overlap(first_from: str | None, first_to: str | None, second_from: str | None, second_to: str | None) -> bool:
    return (first_to is None or second_from is None or first_to > second_from) and (
        second_to is None or first_from is None or second_to > first_from
    )


def _later_end(first: str | None, second: str | None) -> str | None:
    if first is None or second is None:
        return None
    return max(first, second)


def repair_exact_price_duplicates(conn: sqlite3.Connection) -> dict[str, int]:
    """Coalesce overlapping same-source, same-value facts while retaining snapshots.

    Differing amounts, source IDs, dimensions, and non-overlapping validity windows remain
    separate observations. The lowest component ID is deterministic canonical storage.
    """
    ensure_price_observation_table(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO price_component_observation (price_component_id, source_snapshot_id)
        SELECT id, source_snapshot_id FROM price_component WHERE source_snapshot_id IS NOT NULL
        """
    )
    rows = conn.execute(
        """
        SELECT id, model_id, provider_surface_id, source_id, component, unit, currency,
               amount, normalized_usd_per_1m_tokens, tier_condition_json, valid_from, valid_to
        FROM price_component
        ORDER BY model_id, provider_surface_id, source_id, component, unit, currency,
                 amount, normalized_usd_per_1m_tokens, tier_condition_json, valid_from, id
        """
    ).fetchall()
    groups: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
    for row in rows:
        key = row[1:10]
        groups.setdefault(key, []).append(row)

    merged_components = 0
    removed_components = 0
    for group in groups.values():
        canonical: tuple[Any, ...] | None = None
        for row in group:
            identifier, *_, valid_from, valid_to = row
            if canonical is None:
                canonical = row
                continue
            canonical_id = int(canonical[0])
            canonical_from = canonical[10]
            canonical_to = canonical[11]
            if not _intervals_overlap(canonical_from, canonical_to, valid_from, valid_to):
                canonical = row
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO price_component_observation (price_component_id, source_snapshot_id)
                SELECT ?, source_snapshot_id FROM price_component_observation WHERE price_component_id = ?
                """,
                (canonical_id, identifier),
            )
            conn.execute(
                "UPDATE price_component SET valid_to = ? WHERE id = ?",
                (_later_end(canonical_to, valid_to), canonical_id),
            )
            conn.execute("DELETE FROM price_component_observation WHERE price_component_id = ?", (identifier,))
            conn.execute("DELETE FROM price_component WHERE id = ?", (identifier,))
            canonical = (*canonical[:11], _later_end(canonical_to, valid_to))
            merged_components += 1
            removed_components += 1
    observation_links = int(conn.execute("SELECT COUNT(*) FROM price_component_observation").fetchone()[0])
    return {
        "merged_components": merged_components,
        "removed_components": removed_components,
        "observation_links": observation_links,
    }


def repair_price_intervals(conn: sqlite3.Connection) -> dict[str, int]:
    """Coalesce exact duplicates and bound distinct observations by snapshot time."""
    result = repair_exact_price_duplicates(conn)
    rows = conn.execute(
        """
        SELECT pc.id, pc.model_id, pc.provider_surface_id, pc.source_id, pc.component,
               pc.unit, pc.currency, pc.tier_condition_json, ss.fetched_at
        FROM price_component AS pc
        JOIN source_snapshot AS ss ON ss.id = pc.source_snapshot_id
        WHERE pc.source_snapshot_id IS NOT NULL
        ORDER BY pc.model_id, pc.provider_surface_id, pc.source_id, pc.component,
                 pc.unit, pc.currency, pc.tier_condition_json, ss.fetched_at, pc.id
        """
    ).fetchall()
    groups: dict[tuple[Any, ...], list[tuple[Any, ...]]] = {}
    for row in rows:
        groups.setdefault(row[1:8], []).append(row)

    bounded_components = 0
    for group in groups.values():
        snapshot_times = {row[8] for row in group}
        if len(snapshot_times) < 2:
            continue
        by_time: dict[str, list[int]] = {}
        for identifier, *_, fetched_at in group:
            by_time.setdefault(fetched_at, []).append(int(identifier))
        times = sorted(by_time)
        for index, fetched_at in enumerate(times):
            next_fetched_at = times[index + 1] if index + 1 < len(times) else None
            for identifier in by_time[fetched_at]:
                current = conn.execute(
                    "SELECT valid_from, valid_to FROM price_component WHERE id = ?", (identifier,)
                ).fetchone()
                if current != (fetched_at, next_fetched_at):
                    conn.execute(
                        "UPDATE price_component SET valid_from = ?, valid_to = ? WHERE id = ?",
                        (fetched_at, next_fetched_at, identifier),
                    )
                    bounded_components += 1
    result["bounded_components"] = bounded_components
    return result



def main() -> None:
    parser = argparse.ArgumentParser(description="Coalesce exact overlapping price facts without losing snapshot provenance.")
    parser.add_argument("--db", type=Path, default=DB_PATH, help="SQLite database to repair")
    args = parser.parse_args()
    with connect(args.db) as conn:
        print(repair_price_intervals(conn))
        conn.commit()


if __name__ == "__main__":
    main()
