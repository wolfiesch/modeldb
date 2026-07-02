"""Promote direct SWE-bench and Aider leaderboard records into benchmark facts."""
from __future__ import annotations

import json
from typing import Any

from ingest.sources.aider import URL as AIDER_URL
from ingest.sources.swebench import URL as SWEBENCH_URL
from store.spine import link_model


BENCHMARK_CATALOG = {
    "swebench_full_direct": (
        "SWE-bench Full (direct)",
        "coding",
        "percent_resolved",
        SWEBENCH_URL,
    ),
    "swebench_lite_direct": (
        "SWE-bench Lite (direct)",
        "coding",
        "percent_resolved",
        SWEBENCH_URL,
    ),
    "swebench_verified_direct": (
        "SWE-bench Verified (direct)",
        "coding",
        "percent_resolved",
        SWEBENCH_URL,
    ),
    "swebench_multimodal_direct": (
        "SWE-bench Multimodal (direct)",
        "coding",
        "percent_resolved",
        SWEBENCH_URL,
    ),
    "aider_polyglot_direct": (
        "Aider Polyglot (direct)",
        "coding",
        "pass_rate_2",
        AIDER_URL,
    ),
}

SOURCE_IDS = ("swebench", "aider")


def _upsert_benchmark_catalog(conn) -> None:
    for benchmark_id, (name, category, metric_default, source_url) in BENCHMARK_CATALOG.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO benchmark
              (id, name, category, metric_default, higher_is_better, source_url)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (benchmark_id, name, category, metric_default, source_url),
        )


def _delete_prior_results(conn, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    conn.execute(
        f"DELETE FROM benchmark_result WHERE source_snapshot_id IN ({placeholders})",
        snapshot_ids,
    )


def _snapshot_ids(conn) -> list[int]:
    placeholders = ",".join("?" for _ in SOURCE_IDS)
    rows = conn.execute(
        f"SELECT id FROM source_snapshot WHERE source_id IN ({placeholders})",
        SOURCE_IDS,
    ).fetchall()
    return [int(row[0]) for row in rows]


def _source_rows(conn):
    placeholders = ",".join("?" for _ in SOURCE_IDS)
    return conn.execute(
        f"""
        SELECT ss.source_id, smr.source_model_id, smr.source_snapshot_id,
               smr.raw_record_json, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id IN ({placeholders})
        """,
        SOURCE_IDS,
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _compact_json(payload: dict[str, Any]) -> str:
    compact = {key: value for key, value in payload.items() if value is not None}
    return json.dumps(compact, sort_keys=True)


def _eval_condition(source_id: str, pf: dict[str, Any]) -> str:
    if source_id == "swebench":
        return _compact_json(
            {
                "leaderboard": pf.get("leaderboard"),
                "folder": pf.get("folder"),
                "cost": pf.get("cost"),
                "instance_cost": pf.get("instance_cost"),
                "os_model": pf.get("os_model"),
                "os_system": pf.get("os_system"),
            }
        )
    return _compact_json(
        {
            "command": pf.get("command"),
            "edit_format": pf.get("edit_format"),
            "pass_rate_1": pf.get("pass_rate_1"),
            "test_cases": pf.get("test_cases"),
            "total_cost": pf.get("total_cost") or pf.get("cost"),
            "percent_cases_well_formed": pf.get("percent_cases_well_formed"),
        }
    )


def promote_external_benchmarks(conn) -> dict[str, int]:
    """Refresh benchmark_result rows from source-owned SWE-bench and Aider records."""
    _upsert_benchmark_catalog(conn)
    snapshot_ids = _snapshot_ids(conn)
    _delete_prior_results(conn, snapshot_ids)

    inserted = 0
    linked = 0
    unlinked = 0
    skipped = 0
    for source_id, source_model_id, source_snapshot_id, raw_record_json, parsed_fields_json in _source_rows(conn):
        try:
            pf = json.loads(parsed_fields_json) if parsed_fields_json else {}
            benchmark_id = pf.get("benchmark_id")
            if benchmark_id not in BENCHMARK_CATALOG:
                skipped += 1
                continue
            score = _optional_float(pf.get("score"))
            if score is None:
                skipped += 1
                continue

            model_id = link_model(
                conn,
                source_id=source_id,
                source_model_id=source_model_id,
                parsed_fields=pf,
            )
            if model_id is None:
                unlinked += 1
            else:
                linked += 1

            metric = pf.get("metric") or BENCHMARK_CATALOG[benchmark_id][2]
            conn.execute(
                """
                INSERT INTO benchmark_result
                  (model_id, provider_surface_id, benchmark_id, score, metric, rank, ci,
                   votes, eval_condition_json, self_reported, measured_at,
                   source_snapshot_id, raw_record_json)
                VALUES (?, NULL, ?, ?, ?, ?, NULL, NULL, ?, 0, ?, ?, ?)
                """,
                (
                    model_id,
                    benchmark_id,
                    score,
                    metric,
                    _optional_int(pf.get("rank")),
                    _eval_condition(source_id, pf),
                    pf.get("measured_at") or pf.get("date") or pf.get("released"),
                    source_snapshot_id,
                    raw_record_json,
                ),
            )
            inserted += 1
        except Exception:
            skipped += 1

    return {
        "benchmarks": len(BENCHMARK_CATALOG),
        "results_inserted": inserted,
        "linked": linked,
        "unlinked": unlinked,
        "skipped": skipped,
    }
