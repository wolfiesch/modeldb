"""Promote parsed MTEB aggregate records into benchmark facts."""
from __future__ import annotations

import json
from typing import Any

from store.spine import link_model


SOURCE_ID = "mteb"
SOURCE_URL = "https://huggingface.co/datasets/mteb/results"
BASE_CATALOG = {
    "mteb_average": ("MTEB Average", "embedding", "score"),
}


def _delete_prior_results(conn, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    conn.execute(
        f"DELETE FROM benchmark_result WHERE source_snapshot_id IN ({placeholders})",
        snapshot_ids,
    )


def _upsert_benchmark(conn, benchmark_id: str, name: str, category: str,
                      metric_default: str) -> None:
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
        (benchmark_id, name, category, metric_default, SOURCE_URL),
    )


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _benchmark_rows(parsed_fields: dict[str, Any]) -> list[dict[str, Any]]:
    rows = parsed_fields.get("benchmark_results")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]

    if "score" in parsed_fields:
        return [{
            "benchmark_id": parsed_fields.get("benchmark_id", "mteb_average"),
            "name": parsed_fields.get("benchmark_name", "MTEB Average"),
            "category": parsed_fields.get("category", "embedding"),
            "metric": parsed_fields.get("metric", "score"),
            "score": parsed_fields["score"],
            "rank": parsed_fields.get("rank"),
        }]

    return []


def promote_mteb(conn) -> dict[str, int]:
    for benchmark_id, (name, category, metric_default) in BASE_CATALOG.items():
        _upsert_benchmark(conn, benchmark_id, name, category, metric_default)

    snapshot_rows = conn.execute(
        "SELECT id FROM source_snapshot WHERE source_id = ?",
        (SOURCE_ID,),
    ).fetchall()
    snapshot_ids = [int(row[0]) for row in snapshot_rows]
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
    unmatched = 0
    skipped = 0
    catalog_ids = set(BASE_CATALOG)

    for source_model_id, source_snapshot_id, raw_record_json, parsed_fields_json in records:
        if not parsed_fields_json:
            skipped += 1
            continue
        try:
            parsed_fields = json.loads(parsed_fields_json)
            benchmarks = _benchmark_rows(parsed_fields)
            if not benchmarks:
                skipped += 1
                continue

            model_id = link_model(
                conn,
                source_id=SOURCE_ID,
                source_model_id=source_model_id,
                parsed_fields=parsed_fields,
            )
            if model_id is None:
                unmatched += len(benchmarks)
                continue

            for benchmark in benchmarks:
                benchmark_id = str(benchmark["benchmark_id"])
                metric = str(benchmark.get("metric") or "score")
                _upsert_benchmark(
                    conn,
                    benchmark_id,
                    str(benchmark.get("name") or benchmark_id),
                    str(benchmark.get("category") or "embedding"),
                    metric,
                )
                catalog_ids.add(benchmark_id)
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
                        benchmark_id,
                        float(benchmark["score"]),
                        metric,
                        _optional_int(benchmark.get("rank")),
                        _optional_float(benchmark.get("ci")),
                        json.dumps({"source": SOURCE_ID}, sort_keys=True),
                        benchmark.get("measured_at") or parsed_fields.get("measured_at"),
                        source_snapshot_id,
                        raw_record_json,
                    ),
                )
                inserted += 1
        except Exception:
            unmatched += 1

    return {
        "benchmarks": len(catalog_ids),
        "results_inserted": inserted,
        "unmatched": unmatched,
        "skipped": skipped,
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_mteb(c))
        c.commit()
