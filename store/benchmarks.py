"""Promote parsed Epoch benchmark records into canonical benchmark facts."""
from __future__ import annotations

import json

from ingest.base import utcnow
from store.benchmark_scores import canonicalize_fractional_score
from store.spine import link_model


BENCHMARK_CATALOG = {
    "swe_bench_verified": ("SWE-bench Verified", "coding", "percent_resolved"),
    "gpqa_diamond": ("GPQA Diamond", "reasoning", "accuracy"),
    "mmlu": ("MMLU", "knowledge", "accuracy"),
    "math_level_5": ("MATH Level 5", "math", "accuracy"),
    "aider_polyglot": ("Aider Polyglot", "coding", "percent_correct"),
    "livebench": ("LiveBench", "general", "accuracy"),
    "frontiermath": ("FrontierMath", "math", "accuracy"),
    "epoch_capabilities_index": ("Epoch Capabilities Index", "composite", "index"),
}


SOURCE_ID = "epoch"
SOURCE_URL = "https://epoch.ai/benchmarks"


def _upsert_benchmark_catalog(conn) -> None:
    for benchmark_id, (name, category, metric_default) in BENCHMARK_CATALOG.items():
        conn.execute(
            """
            INSERT OR IGNORE INTO benchmark
              (id, name, category, metric_default, higher_is_better, source_url)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (benchmark_id, name, category, metric_default, SOURCE_URL),
        )


def _delete_prior_results(conn, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    conn.execute(
        f"DELETE FROM benchmark_result WHERE source_snapshot_id IN ({placeholders})",
        snapshot_ids,
    )


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def promote_benchmarks(conn) -> dict:
    _upsert_benchmark_catalog(conn)

    snapshot_rows = conn.execute(
        "SELECT id FROM source_snapshot WHERE source_id = ?",
        (SOURCE_ID,),
    ).fetchall()
    snapshot_ids = [int(row[0]) for row in snapshot_rows]
    _delete_prior_results(conn, snapshot_ids)

    rows = conn.execute(
        """
        SELECT smr.source_model_id, smr.source_snapshot_id, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
        """,
        (SOURCE_ID,),
    )

    inserted = 0
    unmatched = 0
    for source_model_id, source_snapshot_id, parsed_fields_json in rows:
        try:
            pf = json.loads(parsed_fields_json)
            benchmark_id = pf["benchmark_id"]
            if benchmark_id not in BENCHMARK_CATALOG:
                unmatched += 1
                continue

            source_score = float(pf["score"])
            metric = BENCHMARK_CATALOG[benchmark_id][2]
            score = canonicalize_fractional_score(source_score, metric)
            model_id = link_model(
                conn,
                source_id=SOURCE_ID,
                source_model_id=source_model_id,
                parsed_fields=pf,
            )
            if model_id is None:
                unmatched += 1
                continue

            conn.execute(
                """
                INSERT INTO benchmark_result
                  (model_id, provider_surface_id, benchmark_id, score, metric, rank, ci,
                   votes, eval_condition_json, self_reported, measured_at,
                   source_snapshot_id, raw_record_json)
                VALUES (?, NULL, ?, ?, ?, NULL, ?, NULL, ?, 0, ?, ?, NULL)
                """,
                (
                    model_id,
                    benchmark_id,
                    score,
                    metric,
                    _optional_float(pf.get("stderr")),
                    json.dumps({
                        "model_version": pf["model_version"],
                        "source_metric": pf.get("score_column"),
                    }),
                    pf.get("release_date"),
                    source_snapshot_id,
                ),
            )
            inserted += 1
        except Exception:
            unmatched += 1

    return {
        "benchmarks": len(BENCHMARK_CATALOG),
        "results_inserted": inserted,
        "unmatched": unmatched,
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_benchmarks(c))
        c.commit()
