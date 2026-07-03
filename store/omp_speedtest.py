"""Promote local OMP speedtest rows into throughput benchmark facts."""
from __future__ import annotations

import json
import math
from typing import Any

from store.spine import link_model

SOURCE_ID = "omp_speedtest"
BENCHMARK_ID = "omp_visible_output_tokens_per_second"
BENCHMARK_NAME = "OMP visible output throughput"
BENCHMARK_CATEGORY = "throughput"
BENCHMARK_METRIC = "visible_tokens_per_second"
SOURCE_URL = "local:~/.omp/agent/skills/omp-model-speedtest/scripts/omp_speedtest.py"


def promote_omp_speedtest(conn) -> dict[str, int]:
    conn.execute(
        """
        INSERT OR IGNORE INTO benchmark (id, name, category, metric_default, higher_is_better, source_url)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (BENCHMARK_ID, BENCHMARK_NAME, BENCHMARK_CATEGORY, BENCHMARK_METRIC, SOURCE_URL),
    )

    snapshot_ids = _source_snapshot_ids(conn)
    if snapshot_ids:
        placeholders = ",".join("?" for _ in snapshot_ids)
        conn.execute(
            f"""
            DELETE FROM benchmark_result
            WHERE benchmark_id = ?
              AND source_snapshot_id IN ({placeholders})
            """,
            [BENCHMARK_ID, *snapshot_ids],
        )

    counts = {"records": 0, "inserted": 0, "unlinked": 0, "skipped": 0}
    for source_model_id, snapshot_id, raw_record_json, parsed_fields_json in _source_rows(conn):
        counts["records"] += 1
        parsed_fields = _json_object(parsed_fields_json)
        score = _positive_float(parsed_fields.get("visibleTokensPerSecond"))
        canonical_slug = parsed_fields.get("canonicalSlug")
        if score is None or not isinstance(canonical_slug, str) or not canonical_slug:
            counts["skipped"] += 1
            continue

        model_id = _model_id_for_slug(conn, canonical_slug)
        if model_id is None:
            model_id = link_model(
                conn,
                source_id=SOURCE_ID,
                source_model_id=source_model_id,
                parsed_fields={"model_version": canonical_slug},
            )
        if model_id is None:
            counts["unlinked"] += 1
            continue

        conn.execute(
            """
            INSERT INTO benchmark_result
              (model_id, provider_surface_id, benchmark_id, score, metric, rank, ci,
               votes, eval_condition_json, self_reported, measured_at,
               source_snapshot_id, raw_record_json)
            VALUES (?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, 0, ?, ?, ?)
            """,
            (
                model_id,
                BENCHMARK_ID,
                score,
                BENCHMARK_METRIC,
                _eval_condition_json(parsed_fields),
                parsed_fields.get("timestamp"),
                snapshot_id,
                raw_record_json,
            ),
        )
        counts["inserted"] += 1

    return counts


def _source_snapshot_ids(conn) -> list[int]:
    rows = conn.execute("SELECT id FROM source_snapshot WHERE source_id = ?", (SOURCE_ID,)).fetchall()
    return [int(row[0]) for row in rows]


def _source_rows(conn):
    return conn.execute(
        """
        SELECT smr.source_model_id, smr.source_snapshot_id, smr.raw_record_json, smr.parsed_fields_json
        FROM source_model_record smr
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
        """,
        (SOURCE_ID,),
    )


def _model_id_for_slug(conn, canonical_slug: str) -> int | None:
    row = conn.execute("SELECT id FROM model WHERE canonical_slug = ?", (canonical_slug,)).fetchone()
    return int(row[0]) if row else None


def _eval_condition_json(parsed_fields: dict[str, Any]) -> str:
    return json.dumps(
        _compact(
            {
                "runId": parsed_fields.get("runId"),
                "canonicalSlug": parsed_fields.get("canonicalSlug"),
                "label": parsed_fields.get("label"),
                "ompSelector": parsed_fields.get("ompSelector"),
                "providerLabel": parsed_fields.get("providerLabel"),
                "prompt": parsed_fields.get("prompt"),
                "runs": parsed_fields.get("runs"),
                "timeoutSeconds": parsed_fields.get("timeoutSeconds"),
                "mode": parsed_fields.get("mode"),
                "durationMs": parsed_fields.get("durationMs"),
                "visibleTokens": parsed_fields.get("visibleTokens"),
                "visibleChars": parsed_fields.get("visibleChars"),
                "visibleCharsPerSecond": parsed_fields.get("visibleCharsPerSecond"),
                "tokenizer": parsed_fields.get("tokenizer"),
                "artifactPath": parsed_fields.get("artifactPath"),
                "sourceHash": parsed_fields.get("sourceHash"),
                "buildMode": parsed_fields.get("buildMode"),
                "scenario": parsed_fields.get("scenario"),
            }
        ),
        sort_keys=True,
    )


def _json_object(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


def _positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
