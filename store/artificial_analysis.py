"""Promote Artificial Analysis rows into benchmark, capability, and price facts."""
from __future__ import annotations

import json
from typing import Any

from ingest.base import utcnow
from resolve.resolver import enqueue_ambiguous
from store.spine import _artificial_analysis_candidates, link_model
from store.price_intervals import repair_price_intervals



SOURCE_ID = "artificialanalysis"
SOURCE_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
CONFIDENCE = 0.9

BENCHMARK_CATALOG = {
    "artificial_analysis_intelligence_index": (
        "Artificial Analysis Intelligence Index",
        "composite",
        "index",
    ),
    "artificial_analysis_coding_index": (
        "Artificial Analysis Coding Index",
        "coding",
        "index",
    ),
    "artificial_analysis_math_index": (
        "Artificial Analysis Math Index",
        "math",
        "index",
    ),
    "mmlu_pro": ("Artificial Analysis MMLU-Pro", "knowledge", "score"),
    "gpqa": ("Artificial Analysis GPQA", "reasoning", "score"),
    "hle": ("Artificial Analysis Humanity's Last Exam", "reasoning", "score"),
    "livecodebench": ("Artificial Analysis LiveCodeBench", "coding", "score"),
    "aime": ("Artificial Analysis AIME", "math", "score"),
    "aime_25": ("Artificial Analysis AIME 2025", "math", "score"),
    "math_500": ("Artificial Analysis MATH-500", "math", "score"),
    "ifbench": ("Artificial Analysis IFBench", "instruction_following", "score"),
    "lcr": ("Artificial Analysis LCR", "coding", "score"),
    "scicode": ("Artificial Analysis SciCode", "coding", "score"),
    "tau2": ("Artificial Analysis Tau2", "agentic", "score"),
    "tau_banking": ("Artificial Analysis Tau Banking", "agentic", "score"),
    "terminalbench_hard": ("Artificial Analysis Terminal-Bench Hard", "agentic", "score"),
    "terminalbench_v2_1": ("Artificial Analysis Terminal-Bench v2.1", "agentic", "score"),
}

CAPABILITY_FIELDS = {
    "median_output_tokens_per_second": "median_output_tokens_per_second",
    "median_time_to_first_token_seconds": "median_time_to_first_token_seconds",
    "median_time_to_first_answer_token": "median_time_to_first_answer_token",
    "artificial_analysis_release_date": "release_date",
}

PRICE_FIELDS = {
    "price_1m_input_tokens": "input_token",
    "price_1m_output_tokens": "output_token",
    "price_1m_blended_3_to_1": "blended_token",
}


def promote_artificial_analysis(conn) -> dict[str, int]:
    """Refresh Artificial Analysis benchmark, speed, latency, and price facts."""
    snapshot_ids = _source_snapshot_ids(conn)
    _delete_prior_results(conn, snapshot_ids)
    _delete_prior_capabilities(conn, snapshot_ids)
    conn.execute("DELETE FROM price_component WHERE source_id = ?", (SOURCE_ID,))

    rows = _source_rows(conn)
    benchmark_ids = _benchmark_ids_present(rows)
    _upsert_benchmark_catalog(conn, benchmark_ids)

    results_inserted = 0
    capabilities_inserted = 0
    prices_inserted = 0
    linked = 0
    unlinked = 0
    queue_cleared = 0
    skipped = 0
    valid_from = utcnow()

    for source_record_id, source_model_id, source_snapshot_id, raw_record_json, parsed_fields_json in rows:
        parsed_fields = _parsed_fields(parsed_fields_json)
        if not parsed_fields:
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
            _enqueue_resolution_review(conn, source_record_id=source_record_id, parsed_fields=parsed_fields)
        else:
            linked += 1
            queue_cleared += _clear_resolution_reviews(conn, source_record_id=source_record_id)

        evaluations = parsed_fields.get("evaluations")
        if not isinstance(evaluations, dict):
            evaluations = {
                key: parsed_fields.get(key)
                for key in BENCHMARK_CATALOG
                if key in parsed_fields
            }

        for benchmark_id, score in evaluations.items():
            if benchmark_id not in BENCHMARK_CATALOG:
                continue
            results_inserted += _insert_result(
                conn,
                model_id=model_id,
                benchmark_id=benchmark_id,
                score=score,
                source_snapshot_id=source_snapshot_id,
                raw_record_json=raw_record_json,
                parsed_fields=parsed_fields,
            )

        if model_id is None:
            continue

        for capability, field in CAPABILITY_FIELDS.items():
            raw_value = parsed_fields.get(field)
            value = str(raw_value).strip() if field == "release_date" and raw_value else _optional_float(raw_value)
            if value is None or value == "":
                continue
            _insert_capability(
                conn,
                model_id=model_id,
                capability=capability,
                value=str(value),
                source_snapshot_id=source_snapshot_id,
            )
            capabilities_inserted += 1

        pricing = parsed_fields.get("pricing")
        if not isinstance(pricing, dict):
            pricing = {
                key: parsed_fields.get(key)
                for key in PRICE_FIELDS
                if key in parsed_fields
            }
        price_condition = {
            key: parsed_fields[key]
            for key in ("model_version", "slug")
            if parsed_fields.get(key)
        }
        if not price_condition:
            price_condition = {"source_model_id": source_model_id}
        tier_condition_json = json.dumps(price_condition, sort_keys=True)
        for field, component in PRICE_FIELDS.items():
            amount = _optional_float(pricing.get(field))
            if amount is None:
                continue
            _insert_price(
                conn,
                model_id=model_id,
                component=component,
                amount=amount,
                source_snapshot_id=source_snapshot_id,
                valid_from=valid_from,
                tier_condition_json=tier_condition_json,
            )
            prices_inserted += 1

    repair_price_intervals(conn)

    return {
        "benchmarks": len(benchmark_ids),
        "results_inserted": results_inserted,
        "capabilities_inserted": capabilities_inserted,
        "prices_inserted": prices_inserted,
        "linked": linked,
        "unlinked": unlinked,
        "queue_cleared": queue_cleared,
        "skipped": skipped,
    }


def _source_snapshot_ids(conn) -> list[int]:
    rows = conn.execute(
        "SELECT id FROM source_snapshot WHERE source_id = ?",
        (SOURCE_ID,),
    ).fetchall()
    return [int(row[0]) for row in rows]


def _source_rows(conn) -> list[tuple[int, str, int, str | None, str | None]]:
    return conn.execute(
        """
        SELECT smr.id, smr.source_model_id, smr.source_snapshot_id, smr.raw_record_json, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
        """,
        (SOURCE_ID,),
    ).fetchall()


def _delete_prior_results(conn, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    conn.execute(
        f"DELETE FROM benchmark_result WHERE source_snapshot_id IN ({placeholders})",
        snapshot_ids,
    )


def _delete_prior_capabilities(conn, snapshot_ids: list[int]) -> None:
    if not snapshot_ids:
        return
    placeholders = ",".join("?" for _ in snapshot_ids)
    conn.execute(
        f"DELETE FROM model_capability WHERE source_snapshot_id IN ({placeholders})",
        snapshot_ids,
    )


def _benchmark_ids_present(rows: list[tuple[int, str, int, str | None, str | None]]) -> set[str]:
    present: set[str] = set()
    for _source_record_id, _source_model_id, _source_snapshot_id, _raw_record_json, parsed_fields_json in rows:
        parsed_fields = _parsed_fields(parsed_fields_json)
        evaluations = parsed_fields.get("evaluations")
        if isinstance(evaluations, dict):
            candidates = evaluations.items()
        else:
            candidates = ((key, parsed_fields.get(key)) for key in BENCHMARK_CATALOG)
        for benchmark_id, score in candidates:
            if benchmark_id in BENCHMARK_CATALOG and _optional_float(score) is not None:
                present.add(benchmark_id)
    return present


def _upsert_benchmark_catalog(conn, benchmark_ids: set[str]) -> None:
    for benchmark_id in sorted(benchmark_ids):
        name, category, metric_default = BENCHMARK_CATALOG[benchmark_id]
        conn.execute(
            """
            INSERT OR IGNORE INTO benchmark
              (id, name, category, metric_default, higher_is_better, source_url)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (benchmark_id, name, category, metric_default, SOURCE_URL),
        )


def _insert_result(
    conn,
    *,
    model_id: int | None,
    benchmark_id: str,
    score: Any,
    source_snapshot_id: int,
    raw_record_json: str | None,
    parsed_fields: dict[str, Any],
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
        VALUES (?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, 0, NULL, ?, ?)
        """,
        (
            model_id,
            benchmark_id,
            numeric_score,
            BENCHMARK_CATALOG[benchmark_id][2],
            json.dumps(_eval_condition(parsed_fields), sort_keys=True),
            source_snapshot_id,
            raw_record_json,
        ),
    )
    return 1


def _insert_capability(
    conn,
    *,
    model_id: int,
    capability: str,
    value: str,
    source_snapshot_id: int,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO model_capability
          (model_id, capability, value, source_snapshot_id, confidence)
        VALUES (?, ?, ?, ?, ?)
        """,
        (model_id, capability, value, source_snapshot_id, CONFIDENCE),
    )


def _insert_price(
    conn,
    *,
    model_id: int,
    component: str,
    amount: float,
    source_snapshot_id: int,
    valid_from: str,
    tier_condition_json: str,
) -> None:
    conn.execute(
        """
        INSERT INTO price_component
          (model_id, provider_surface_id, source_id, component, unit, currency,
           amount, normalized_usd_per_1m_tokens, tier_condition_json, valid_from,
           valid_to, source_snapshot_id)
        VALUES (?, NULL, ?, ?, '1m_tokens', 'USD', ?, ?, ?, ?, NULL, ?)
        """,
        (model_id, SOURCE_ID, component, amount, amount, tier_condition_json, valid_from, source_snapshot_id),
    )


def _clear_resolution_reviews(conn, *, source_record_id: int) -> int:
    cursor = conn.execute(
        """
        DELETE FROM entity_resolution_queue
        WHERE source_record_id = ?
          AND candidate_model_id IS NULL
          AND status = 'pending'
        """,
        (source_record_id,),
    )
    return int(cursor.rowcount or 0)


def _enqueue_resolution_review(conn, *, source_record_id: int, parsed_fields: dict[str, Any]) -> None:
    candidates = _artificial_analysis_candidates(parsed_fields)
    if not candidates:
        return
    enqueue_ambiguous(
        conn,
        source_record_id=source_record_id,
        candidate_model_id=None,
        reason="unresolved artificialanalysis provider-scoped aliases",
        features={
            "source_id": SOURCE_ID,
            "provider_scoped_candidates": candidates,
            "model_creator_slug": parsed_fields.get("model_creator_slug"),
            "model_creator_name": parsed_fields.get("model_creator_name"),
            "slug": parsed_fields.get("slug"),
            "model_name": parsed_fields.get("name") or parsed_fields.get("model_name"),
        },
    )


def _parsed_fields(parsed_fields_json: str | None) -> dict[str, Any]:
    if not parsed_fields_json:
        return {}
    try:
        parsed = json.loads(parsed_fields_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _eval_condition(parsed_fields: dict[str, Any]) -> dict[str, Any]:
    condition = {
        "source_model_id": parsed_fields.get("id"),
        "slug": parsed_fields.get("slug"),
        "model_name": parsed_fields.get("name") or parsed_fields.get("model_name"),
        "model_creator_slug": parsed_fields.get("model_creator_slug"),
        "model_creator_name": parsed_fields.get("model_creator_name"),
    }
    return {key: value for key, value in condition.items() if value not in (None, "")}


def _optional_float(value: Any) -> float | None:
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
