"""Promote archived Open LLM Leaderboard rows into benchmark facts."""
from __future__ import annotations

import json

from store.spine import link_model


SOURCE_ID = "open_llm_lb"
SOURCE_URL = "https://huggingface.co/datasets/open-llm-leaderboard/contents"

AVERAGE_BENCHMARK_ID = "open_llm_lb_average"
COMPONENT_BENCHMARKS = {
    "ifeval": ("open_llm_lb_ifeval", "Open LLM Leaderboard IFEval", "instruction_following"),
    "bbh": ("open_llm_lb_bbh", "Open LLM Leaderboard BBH", "reasoning"),
    "math_l5": ("open_llm_lb_math_l5", "Open LLM Leaderboard MATH Level 5", "math"),
    "gpqa": ("open_llm_lb_gpqa", "Open LLM Leaderboard GPQA", "reasoning"),
    "musr": ("open_llm_lb_musr", "Open LLM Leaderboard MUSR", "reasoning"),
    "mmlu_pro": ("open_llm_lb_mmlu_pro", "Open LLM Leaderboard MMLU-PRO", "knowledge"),
}


def promote_open_llm_lb(conn) -> dict[str, int]:
    """Refresh benchmark_result rows owned by open_llm_lb snapshots."""
    snapshot_ids = _source_snapshot_ids(conn)
    _delete_prior_results(conn, snapshot_ids)

    rows = conn.execute(
        """
        SELECT smr.source_model_id, smr.source_snapshot_id, smr.raw_record_json, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
        """,
        (SOURCE_ID,),
    ).fetchall()

    component_keys = _component_keys_present(rows)
    benchmark_count = _upsert_benchmark_catalog(conn, component_keys)

    inserted = 0
    linked = 0
    unlinked = 0
    skipped = 0
    for source_model_id, source_snapshot_id, raw_record_json, parsed_fields_json in rows:
        try:
            parsed_fields = json.loads(parsed_fields_json) if parsed_fields_json else {}
            if not isinstance(parsed_fields, dict):
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

            measured_at = parsed_fields.get("submission_date") or parsed_fields.get("upload_to_hub_date")
            inserted += _insert_score(
                conn,
                model_id=model_id,
                benchmark_id=AVERAGE_BENCHMARK_ID,
                score=parsed_fields.get("average_score"),
                measured_at=measured_at,
                source_snapshot_id=source_snapshot_id,
                raw_record_json=raw_record_json,
                parsed_fields=parsed_fields,
            )

            component_scores = parsed_fields.get("component_scores")
            if isinstance(component_scores, dict):
                for component_key, score in component_scores.items():
                    spec = COMPONENT_BENCHMARKS.get(component_key)
                    if spec is None:
                        continue
                    inserted += _insert_score(
                        conn,
                        model_id=model_id,
                        benchmark_id=spec[0],
                        score=score,
                        measured_at=measured_at,
                        source_snapshot_id=source_snapshot_id,
                        raw_record_json=raw_record_json,
                        parsed_fields=parsed_fields,
                    )
        except Exception:
            skipped += 1

    return {
        "benchmarks": benchmark_count,
        "results_inserted": inserted,
        "linked": linked,
        "unlinked": unlinked,
        "skipped": skipped,
    }


def _source_snapshot_ids(conn) -> list[int]:
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


def _component_keys_present(rows) -> set[str]:
    present: set[str] = set()
    for _source_model_id, _source_snapshot_id, _raw_record_json, parsed_fields_json in rows:
        try:
            parsed_fields = json.loads(parsed_fields_json) if parsed_fields_json else {}
        except json.JSONDecodeError:
            continue
        component_scores = parsed_fields.get("component_scores") if isinstance(parsed_fields, dict) else None
        if not isinstance(component_scores, dict):
            continue
        for component_key, score in component_scores.items():
            if component_key in COMPONENT_BENCHMARKS and _optional_float(score) is not None:
                present.add(component_key)
    return present


def _upsert_benchmark_catalog(conn, component_keys: set[str]) -> int:
    catalog_rows = [
        (AVERAGE_BENCHMARK_ID, "Open LLM Leaderboard Average", "composite", "score"),
    ]
    for component_key in sorted(component_keys):
        benchmark_id, name, category = COMPONENT_BENCHMARKS[component_key]
        catalog_rows.append((benchmark_id, name, category, "score"))

    for benchmark_id, name, category, metric_default in catalog_rows:
        conn.execute(
            """
            INSERT OR IGNORE INTO benchmark
              (id, name, category, metric_default, higher_is_better, source_url)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (benchmark_id, name, category, metric_default, SOURCE_URL),
        )
    return len(catalog_rows)


def _insert_score(
    conn,
    *,
    model_id: int | None,
    benchmark_id: str,
    score,
    measured_at,
    source_snapshot_id: int,
    raw_record_json: str | None,
    parsed_fields: dict,
) -> int:
    numeric_score = _optional_float(score)
    if numeric_score is None:
        return 0

    conn.execute(
        """
        INSERT INTO benchmark_result
          (model_id, provider_surface_id, benchmark_id, score, metric, rank, ci,
           votes, eval_condition_json, self_reported, measured_at,
           source_snapshot_id, raw_record_json)
        VALUES (?, NULL, ?, ?, 'score', NULL, NULL, NULL, ?, 0, ?, ?, ?)
        """,
        (
            model_id,
            benchmark_id,
            numeric_score,
            json.dumps(_eval_condition(parsed_fields), sort_keys=True),
            measured_at,
            source_snapshot_id,
            raw_record_json,
        ),
    )
    return 1


def _eval_condition(parsed_fields: dict) -> dict:
    condition = {
        "source_model_id": parsed_fields.get("source_model_id"),
        "model_name": parsed_fields.get("model_name"),
        "fullname": parsed_fields.get("fullname"),
        "base_model": parsed_fields.get("base_model"),
    }
    return {key: value for key, value in condition.items() if value not in (None, "")}


def _optional_float(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None
