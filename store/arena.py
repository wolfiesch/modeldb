"""Promote parsed LMArena leaderboard records into benchmark timeseries facts."""
from __future__ import annotations

import json

from ingest.base import utcnow
from store.spine import link_model


SOURCE_ID = "lmarena"
SOURCE_URL = "https://lmarena.ai"

BENCHMARK_CATALOG = {
    "lmarena_text_overall": (
        "LMArena Text (Overall)",
        "arena_elo",
        "elo",
    ),
    "lmarena_text_coding": (
        "LMArena Text (Coding)",
        "arena_elo",
        "elo",
    ),
}

CATEGORY_TO_BENCHMARK = {
    "overall": "lmarena_text_overall",
    "coding": "lmarena_text_coding",
}




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


def _optional_int(value) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _confidence_interval(pf: dict) -> float | None:
    lower = _optional_float(pf.get("rating_lower"))
    upper = _optional_float(pf.get("rating_upper"))
    if lower is None or upper is None:
        return None
    return (upper - lower) / 2


def promote_arena(conn) -> dict:
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
    linked = 0
    unlinked = 0
    for _source_model_id, source_snapshot_id, parsed_fields_json in rows:
        try:
            pf = json.loads(parsed_fields_json)
            benchmark_id = CATEGORY_TO_BENCHMARK.get(pf["category"])
            if benchmark_id is None:
                continue

            score = float(pf["rating"])
            model_id = link_model(
                conn,
                source_id=SOURCE_ID,
                source_model_id=pf["model_name"],
                parsed_fields=pf,
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
                VALUES (?, NULL, ?, ?, 'elo', ?, ?, ?, ?, 0, ?, ?, NULL)
                """,
                (
                    model_id,
                    benchmark_id,
                    score,
                    _optional_int(pf.get("rank")),
                    _confidence_interval(pf),
                    _optional_int(pf.get("vote_count")),
                    json.dumps(
                        {
                            "model_name": pf["model_name"],
                            "category": pf["category"],
                            "organization": pf.get("organization"),
                        },
                        sort_keys=True,
                    ),
                    pf["publish_date"],
                    source_snapshot_id,
                ),
            )
            inserted += 1
        except Exception:
            unlinked += 1

    return {
        "benchmarks": len(BENCHMARK_CATALOG),
        "results_inserted": inserted,
        "linked": linked,
        "unlinked": unlinked,
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_arena(c))
        c.commit()
