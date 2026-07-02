"""Promote parsed DeepSWE leaderboard records into benchmark facts."""
from __future__ import annotations

import json
from typing import Any

from ingest.sources.deepswe import BENCHMARK_ID, LIVE_URL
from store.spine import link_model


SOURCE_ID = "deepswe"
BENCHMARK_NAME = "DeepSWE"
BENCHMARK_CATEGORY = "coding"
BENCHMARK_METRIC = "percent_resolved"


_EVAL_KEYS = (
    "agent",
    "scaffold",
    "harness",
    "config",
    "reasoning_effort",
    "source",
    "n_runs",
    "ci_method",
    "n_attempted",
    "n_passed",
    "n_tasks_attempted",
    "n_tasks_passed_any",
    "pass_at_4",
    "mean_cost_usd",
    "median_cost_usd",
    "mean_output_tokens",
    "median_output_tokens",
    "mean_input_tokens",
    "median_input_tokens",
    "mean_duration_seconds",
    "median_duration_seconds",
    "mean_agent_steps",
    "median_agent_steps",
    "median_peak_context_tokens",
    "median_output_tokens_to_pass",
    "scope",
    "unit",
    "generated_at",
    "n_tasks_in_set",
    "latest_job_name",
    "latest_job_finished_at",
)


def _upsert_benchmark(conn) -> None:
    conn.execute(
        """
        INSERT INTO benchmark
          (id, name, category, metric_default, higher_is_better, source_url)
        VALUES (?, ?, ?, ?, 1, ?)
        ON CONFLICT(id) DO UPDATE SET
          name = excluded.name,
          category = excluded.category,
          metric_default = excluded.metric_default,
          higher_is_better = excluded.higher_is_better,
          source_url = excluded.source_url
        """,
        (BENCHMARK_ID, BENCHMARK_NAME, BENCHMARK_CATEGORY, BENCHMARK_METRIC, LIVE_URL),
    )


def _snapshot_ids(conn) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM source_snapshot WHERE source_id = ?",
        (SOURCE_ID,),
    ).fetchall()
    return [int(row[0]) for row in rows]


def _delete_prior_results(conn, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    conn.execute(
        f"DELETE FROM benchmark_result WHERE source_snapshot_id IN ({placeholders})",
        snapshot_ids,
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps({key: value for key, value in payload.items() if value is not None}, sort_keys=True)


def _eval_condition(parsed_fields: dict[str, Any]) -> str:
    return _compact_json({key: parsed_fields.get(key) for key in _EVAL_KEYS})


def promote_deepswe(conn) -> dict[str, int]:
    """Refresh benchmark_result rows owned by DeepSWE snapshots."""
    _upsert_benchmark(conn)
    snapshot_ids = _snapshot_ids(conn)
    _delete_prior_results(conn, snapshot_ids)

    records = conn.execute(
        """
        SELECT smr.source_model_id, smr.source_snapshot_id, smr.raw_record_json,
               smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
        """,
        (SOURCE_ID,),
    )

    inserted = 0
    linked = 0
    unlinked = 0
    skipped = 0
    for source_model_id, source_snapshot_id, raw_record_json, parsed_fields_json in records:
        if not parsed_fields_json:
            skipped += 1
            continue
        try:
            parsed_fields = json.loads(parsed_fields_json)
            score = _optional_float(parsed_fields.get("score"))
            if score is None:
                skipped += 1
                continue

            model_id = link_model(
                conn,
                source_id=SOURCE_ID,
                source_model_id=source_model_id,
                parsed_fields=parsed_fields,
            )
            if model_id is None:
                unlinked += 1
            else:
                linked += 1

            conn.execute(
                """
                INSERT INTO benchmark_result
                  (model_id, provider_surface_id, benchmark_id, score, metric, rank, ci,
                   votes, eval_condition_json, self_reported, measured_at,
                   source_snapshot_id, raw_record_json)
                VALUES (?, NULL, ?, ?, ?, ?, ?, NULL, ?, 0, ?, ?, ?)
                """,
                (
                    model_id,
                    str(parsed_fields.get("benchmark_id") or BENCHMARK_ID),
                    score,
                    str(parsed_fields.get("metric") or BENCHMARK_METRIC),
                    _optional_int(parsed_fields.get("rank")),
                    _optional_float(parsed_fields.get("ci") or parsed_fields.get("ci_half")),
                    _eval_condition(parsed_fields),
                    parsed_fields.get("measured_at"),
                    source_snapshot_id,
                    raw_record_json,
                ),
            )
            inserted += 1
        except Exception:
            skipped += 1

    return {
        "benchmarks": 1,
        "results_inserted": inserted,
        "linked": linked,
        "unlinked": unlinked,
        "skipped": skipped,
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_deepswe(c))
        c.commit()
