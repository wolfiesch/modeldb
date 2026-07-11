"""DeepSWE leaderboard source parser."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ingest.base import SourceModelRecord, SourceParser


LIVE_URL = "https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json"
FALLBACK_URL = "https://deepswe.datacurve.ai/artifacts/v1/leaderboard-live.json"
LEGACY_URL = "https://deepswe.datacurve.ai/artifacts/leaderboard.json"
USER_AGENT = "modeldb-ingest/0.1"
BENCHMARK_ID = "deepswe"


_MODEL_KEYS = (
    "model",
    "model_name",
    "name",
    "model_id",
    "model_slug",
)
_SCORE_KEYS = (
    "pass_rate",
    "pass_at_1",
    "resolved",
    "percent_resolved",
    "% resolved",
    "score",
)
_RANK_KEYS = ("rank", "place", "position")
_DATE_KEYS = ("measured_at", "date", "updated_at", "finished_at", "created_at")
_CI_KEYS = ("ci_half", "ci", "error", "error_interval", "confidence_interval")
_SETTINGS_KEYS = (
    "agent",
    "scaffold",
    "harness",
    "config",
    "reasoning_effort",
    "source",
    "n_runs",
    "ci_method",
)
_EFFICIENCY_KEYS = (
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
)


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"


def _first_value(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if not value:
            return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(float(value))


def _score_percent(row: dict[str, Any]) -> tuple[float, str] | tuple[None, None]:
    for key in _SCORE_KEYS:
        score = _optional_float(row.get(key))
        if score is None:
            continue
        if key in {"pass_rate", "pass_at_1", "resolved"} and score <= 1:
            return score * 100, key
        if key in {"score", "percent_resolved", "% resolved"} and score <= 1:
            return score * 100, key
        return score, key
    return None, None


def _percent_interval(value: Any) -> float | None:
    interval = _optional_float(value)
    if interval is None:
        return None
    return interval * 100 if interval <= 1 else interval


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("rows", "results", "leaderboard", "leaderboards", "data"):
        rows = payload.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, dict):
            nested = _rows_from_payload(rows)
            if nested:
                return nested
    return []


def _payload_context(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    latest_job = payload.get("latest_job") if isinstance(payload.get("latest_job"), dict) else {}
    return {
        "scope": payload.get("scope"),
        "unit": payload.get("unit"),
        "generated_at": payload.get("generated_at"),
        "n_tasks_in_set": payload.get("n_tasks_in_set"),
        "latest_job_name": latest_job.get("name"),
        "latest_job_finished_at": latest_job.get("finished_at"),
    }


class DeepSWEParser(SourceParser):
    """Parse DeepSWE static JSON artifact rows into source-native records."""

    source_id = "deepswe"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        last_error: Exception | None = None
        for url in (LIVE_URL, FALLBACK_URL, LEGACY_URL):
            request = Request(url, headers={"User-Agent": USER_AGENT})
            try:
                with urlopen(request) as response:
                    raw = response.read()
                    headers = response.headers
                    return response.geturl(), raw, {
                        "etag": headers.get("ETag"),
                        "last_modified": headers.get("Last-Modified"),
                    }
            except (HTTPError, URLError) as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("DeepSWE artifact fetch failed")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        context = _payload_context(payload)
        rows = _rows_from_payload(payload)

        for index, row in enumerate(rows, start=1):
            model_name = str(_first_value(row, _MODEL_KEYS) or "").strip()
            score, score_key = _score_percent(row)
            if not model_name or score is None:
                continue

            rank = _optional_int(_first_value(row, _RANK_KEYS))
            measured_at = _first_value(row, _DATE_KEYS) or context.get("generated_at") or context.get("latest_job_finished_at")
            ci = _percent_interval(_first_value(row, _CI_KEYS))
            parsed_fields: dict[str, Any] = {
                "benchmark_id": BENCHMARK_ID,
                "benchmark_name": "DeepSWE",
                "category": "coding",
                "metric": "percent_resolved",
                "score": score,
                "score_source_field": score_key,
                "model_name": model_name,
                "model_version": model_name,
                "rank": rank,
                "measured_at": measured_at,
                "ci": ci,
                "ci_lo": _percent_interval(row.get("ci_lo")),
                "ci_hi": _percent_interval(row.get("ci_hi")),
                "ci_half": _percent_interval(row.get("ci_half")),
                "row_index": index,
            }
            for key in _SETTINGS_KEYS + _EFFICIENCY_KEYS:
                if key in row:
                    parsed_fields[key] = row.get(key)
            for key, value in context.items():
                if value is not None:
                    parsed_fields[key] = value

            source_row_id = row.get("config") or row.get("id") or f"{model_name}-{index}"
            yield SourceModelRecord(
                source_model_id=f"{BENCHMARK_ID}::{_slug(source_row_id)}",
                display_name=model_name,
                provider_name=None,
                raw_record_json=json.dumps(row, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )


DeepSWE = DeepSWEParser
