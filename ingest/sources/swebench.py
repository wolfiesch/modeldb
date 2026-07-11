"""SWE-bench leaderboard source parser."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from urllib.request import urlopen

from ingest.base import SourceModelRecord, SourceParser


URL = "https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json"

LEADERBOARD_BENCHMARK_IDS = {
    "full": "swebench_full_direct",
    "test": "swebench_full_direct",
    "lite": "swebench_lite_direct",
    "verified": "swebench_verified_direct",
    "multimodal": "swebench_multimodal_direct",
}


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if not value:
            return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _score_percent(row: dict) -> float | None:
    for key in ("resolved", "% resolved", "resolve_rate", "score"):
        score = _optional_float(row.get(key))
        if score is not None:
            return score * 100 if key == "resolve_rate" and score <= 1 else score
    return None


class SWEBenchParser(SourceParser):
    """Parse SWE-bench leaderboards.json rows into source-native benchmark records."""

    source_id = "swebench"
    parser_version = "0.2.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        with urlopen(URL) as response:
            raw = response.read()
            headers = response.headers
            meta = {
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
            }
            return response.geturl(), raw, meta

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        leaderboards = payload.get("leaderboards", []) if isinstance(payload, dict) else []
        if not isinstance(leaderboards, list):
            return

        for leaderboard in leaderboards:
            if not isinstance(leaderboard, dict):
                continue
            leaderboard_name = str(leaderboard.get("name") or "").strip()
            benchmark_id = LEADERBOARD_BENCHMARK_IDS.get(leaderboard_name.lower())
            if benchmark_id is None:
                continue
            results = leaderboard.get("results", [])
            if not isinstance(results, list):
                continue

            for row in results:
                if not isinstance(row, dict):
                    continue
                model_name = str(row.get("name") or row.get("model") or "").strip()
                score = _score_percent(row)
                if not model_name or score is None:
                    continue

                source_row_id = row.get("folder") or f"{model_name}-{row.get('date') or ''}"
                parsed_fields = {
                    "benchmark_id": benchmark_id,
                    "leaderboard": leaderboard_name,
                    "model_name": model_name,
                    "model_version": model_name,
                    "score": score,
                    "score_percent_resolved": score,
                    "metric": "percent_resolved",
                    "rank": _optional_int(row.get("rank")),
                    "measured_at": row.get("date"),
                    "date": row.get("date"),
                    "cost": _optional_float(row.get("cost")),
                    "instance_cost": _optional_float(row.get("instance_cost")),
                    "folder": row.get("folder"),
                    "os_model": row.get("os_model"),
                    "os_system": row.get("os_system"),
                }
                yield SourceModelRecord(
                    source_model_id=f"{benchmark_id}::{_slug(source_row_id)}",
                    display_name=model_name,
                    provider_name=None,
                    raw_record_json=json.dumps(row, sort_keys=True),
                    parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
                )


SWEBench = SWEBenchParser
