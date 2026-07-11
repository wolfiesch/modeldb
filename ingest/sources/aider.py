"""Aider polyglot leaderboard source parser."""
from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.request import urlopen

from ingest.base import SourceModelRecord, SourceParser


URL = "https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml"


def _parse_scalar(value: str):
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    lowered = value.lower()
    if lowered == "null":
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if any(ch in value for ch in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value


def _parse_simple_yaml_list(text: str) -> list[dict]:
    rows: list[dict] = []
    current: dict | None = None
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            if current:
                rows.append(current)
            current = {}
            stripped = stripped[2:].strip()
            if not stripped:
                continue
        if current is None or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if key:
            current[key] = _parse_scalar(value)
    if current:
        rows.append(current)
    return rows


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if not value:
            return None
    return float(value)


class AiderParser(SourceParser):
    """Parse Aider's stdlib-friendly YAML leaderboard into source-native rows."""

    source_id = "aider"
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
        rows = _parse_simple_yaml_list(raw.decode("utf-8"))
        for row in rows:
            model_name = str(row.get("model") or "").strip()
            score = _optional_float(row.get("pass_rate_2"))
            if not model_name or score is None:
                continue
            measured_at = row.get("date") or row.get("released")
            parsed_fields = {
                "benchmark_id": "aider_polyglot_direct",
                "model_name": model_name,
                "model_version": model_name,
                "score": score,
                "pass_rate_2": score,
                "pass_rate_1": _optional_float(row.get("pass_rate_1")),
                "metric": "pass_rate_2",
                "command": row.get("command"),
                "date": row.get("date"),
                "released": row.get("released"),
                "measured_at": measured_at,
                "cost": _optional_float(row.get("cost") or row.get("total_cost")),
                "total_cost": _optional_float(row.get("total_cost")),
                "edit_format": row.get("edit_format"),
                "test_cases": row.get("test_cases"),
                "percent_cases_well_formed": _optional_float(row.get("percent_cases_well_formed")),
            }
            source_row_id = row.get("dirname") or f"{model_name}-{measured_at or ''}"
            yield SourceModelRecord(
                source_model_id=f"aider_polyglot_direct::{source_row_id}",
                display_name=model_name,
                provider_name=None,
                raw_record_json=json.dumps(row, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )


Aider = AiderParser
