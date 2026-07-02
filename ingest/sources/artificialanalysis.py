"""Artificial Analysis LLM model source parser."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from collections.abc import Iterator
from typing import Any, Callable
from urllib.request import Request, urlopen

from ingest.base import REPO_ROOT, SourceModelRecord, SourceParser


URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
PRIMARY_API_KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"
LEGACY_API_KEY_ENV = "ARTIFICIALANALYSIS_API_KEY"
CACHE_TTL = timedelta(hours=24)


def fetch_with_cache(
    conn,
    *,
    now: datetime | None = None,
    repo_root: Path = REPO_ROOT,
    urlopen_fn: Callable = urlopen,
    cache_ttl: timedelta = CACHE_TTL,
) -> tuple[str, bytes, dict]:
    """Return a fresh AA raw payload from source_snapshot before using the API."""
    cached = _fresh_cached_snapshot(conn, now=now, repo_root=repo_root, cache_ttl=cache_ttl)
    if cached is not None:
        return cached
    return _fetch_live(urlopen_fn=urlopen_fn)


def _fresh_cached_snapshot(
    conn,
    *,
    now: datetime | None,
    repo_root: Path,
    cache_ttl: timedelta,
) -> tuple[str, bytes, dict] | None:
    current = now or datetime.now(timezone.utc)
    rows = conn.execute(
        """
        SELECT url, raw_path, fetched_at, etag, last_modified
        FROM source_snapshot
        WHERE source_id = ? AND url = ? AND parser_version = ?
        ORDER BY fetched_at DESC, id DESC
        LIMIT 10
        """,
        (ArtificialAnalysisParser.source_id, URL, ArtificialAnalysisParser.parser_version),
    ).fetchall()
    for url, raw_path, fetched_at, etag, last_modified in rows:
        fetched = _parse_snapshot_time(fetched_at)
        if fetched is None or current - fetched > cache_ttl:
            continue
        path = repo_root / raw_path
        if not path.exists():
            continue
        return url, path.read_bytes(), {"etag": etag, "last_modified": last_modified, "cached": True}
    return None


def _parse_snapshot_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fetch_live(*, urlopen_fn: Callable = urlopen) -> tuple[str, bytes, dict]:
    api_key = os.environ.get(PRIMARY_API_KEY_ENV) or os.environ.get(LEGACY_API_KEY_ENV)
    if not api_key:
        raise NotImplementedError(
            f"Artificial Analysis fetch requires {PRIMARY_API_KEY_ENV} "
            f"(or legacy {LEGACY_API_KEY_ENV}) and is opt-in to avoid API quota use."
        )

    request = Request(URL, headers={"x-api-key": api_key, "Accept": "application/json"})
    with urlopen_fn(request) as response:
        raw = response.read()
        headers = response.headers
        meta = {
            "etag": headers.get("ETag"),
            "last_modified": headers.get("Last-Modified"),
        }
        return response.geturl(), raw, meta


EVALUATION_KEYS = (
    "artificial_analysis_intelligence_index",
    "artificial_analysis_coding_index",
    "artificial_analysis_math_index",
    "mmlu_pro",
    "gpqa",
    "hle",
    "livecodebench",
    "aime",
    "aime_25",
    "math_500",
    "ifbench",
    "lcr",
    "scicode",
    "tau2",
    "tau_banking",
    "terminalbench_hard",
    "terminalbench_v2_1",
)

PRICE_KEYS = (
    "price_1m_input_tokens",
    "price_1m_output_tokens",
    "price_1m_blended_3_to_1",
)

CAPABILITY_KEYS = (
    "median_output_tokens_per_second",
    "median_time_to_first_token_seconds",
    "median_time_to_first_answer_token",
    "release_date",
)


class ArtificialAnalysisParser(SourceParser):
    """Parse Artificial Analysis API rows into source-native model records."""

    source_id = "artificialanalysis"
    parser_version = "0.2.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        return _fetch_live()

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        for row in _iter_rows(payload):
            parsed_fields = _parsed_fields(row)
            source_model_id = parsed_fields.get("id") or parsed_fields.get("slug")
            if not source_model_id:
                source_model_id = _slug(parsed_fields.get("name") or row.get("name"))
            if not source_model_id:
                continue

            yield SourceModelRecord(
                source_model_id=str(source_model_id),
                display_name=parsed_fields.get("name"),
                provider_name=parsed_fields.get("model_creator_name"),
                raw_record_json=json.dumps(row, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )


def _iter_rows(payload: Any) -> Iterator[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = (
            payload.get("data")
            or payload.get("models")
            or payload.get("results")
            or payload.get("items")
            or []
        )
    else:
        rows = []

    if isinstance(rows, dict):
        rows = rows.values()

    for row in rows:
        if isinstance(row, dict):
            yield row


def _parsed_fields(row: dict[str, Any]) -> dict[str, Any]:
    creator = row.get("model_creator")
    creator = creator if isinstance(creator, dict) else {}
    evaluations = row.get("evaluations")
    evaluations = evaluations if isinstance(evaluations, dict) else {}
    pricing = row.get("pricing")
    pricing = pricing if isinstance(pricing, dict) else {}

    parsed: dict[str, Any] = {
        "id": _text(row.get("id")),
        "slug": _text(row.get("slug")),
        "name": _text(row.get("name")),
        "model_name": _text(row.get("name")),
        "model_version": _model_version(row, creator),
        "model_creator_id": _text(creator.get("id") or row.get("model_creator_id")),
        "model_creator_slug": _text(creator.get("slug") or row.get("model_creator_slug")),
        "model_creator_name": _text(creator.get("name") or row.get("model_creator_name")),
    }

    parsed["evaluations"] = _numeric_fields(evaluations, row, EVALUATION_KEYS)
    parsed["pricing"] = _numeric_fields(pricing, row, PRICE_KEYS)

    for key in CAPABILITY_KEYS:
        value = row.get(key)
        if value is None:
            value = _nested_lookup(row, key)
        if value is not None:
            parsed[key] = _text(value) if key == "release_date" else _optional_float(value)

    for key, value in parsed["evaluations"].items():
        parsed[key] = value
    for key, value in parsed["pricing"].items():
        parsed[key] = value

    return {key: value for key, value in parsed.items() if value not in (None, "", {}, [])}


def _numeric_fields(primary: dict[str, Any], row: dict[str, Any], keys: tuple[str, ...]) -> dict[str, float]:
    fields: dict[str, float] = {}
    for key in keys:
        value = _optional_float(_nested_lookup(primary, key))
        if value is None:
            value = _optional_float(row.get(key))
        if value is None:
            value = _optional_float(_nested_lookup(row, key))
        if value is not None:
            fields[key] = value
    return fields


def _nested_lookup(value: Any, key: str) -> Any:
    if not isinstance(value, dict):
        return None
    if key in value:
        return value[key]
    for nested in value.values():
        found = _nested_lookup(nested, key)
        if found is not None:
            return found
    return None


def _model_version(row: dict[str, Any], creator: dict[str, Any]) -> str | None:
    name = _text(row.get("name"))
    creator_slug = _text(creator.get("slug") or row.get("model_creator_slug"))
    if name and creator_slug:
        return f"{creator_slug}/{name}"
    return name or _text(row.get("slug") or row.get("id"))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


ArtificialAnalysis = ArtificialAnalysisParser
