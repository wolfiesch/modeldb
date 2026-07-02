"""MTEB leaderboard/results source parser.

The official Hugging Face `mteb/results` dataset is currently published as
large parquet shards.  This parser intentionally stays stdlib-only: fetch()
reports the unsupported live format, while parse() accepts caller-supplied
aggregate JSON or CSV rows exported from the official leaderboard/results data.
"""
from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Iterator
from io import StringIO
from typing import Any

from ingest.base import SourceModelRecord, SourceParser


SOURCE_URL = "https://huggingface.co/datasets/mteb/results"
UNSUPPORTED_PARQUET_MESSAGE = (
    "MTEB official Hugging Face results are parquet-only; stdlib ingestion "
    "cannot fetch them without datasets/pyarrow. Supply JSON or CSV aggregate "
    "leaderboard rows to MTEBParser.parse()."
)

_MODEL_KEYS = (
    "model",
    "Model",
    "model_name",
    "Model Name",
    "model_id",
    "hf_model_id",
    "name",
    "Name",
)
_SCORE_KEYS = (
    "average",
    "Average",
    "avg",
    "Avg",
    "score",
    "Score",
    "MTEB Average",
    "MTEB average",
    "Mean",
)
_RANK_KEYS = ("rank", "Rank", "leaderboard_rank", "Leaderboard Rank")
_DATE_KEYS = ("date", "Date", "eval_date", "evaluation_date", "submission_date", "created_at")
_PROVIDER_KEYS = ("provider", "Provider", "organization", "Organization", "org", "Org")

_COMPONENT_COLUMNS = {
    "Classification": "Classification",
    "Clustering": "Clustering",
    "PairClassification": "Pair Classification",
    "Pair Classification": "Pair Classification",
    "Reranking": "Reranking",
    "Retrieval": "Retrieval",
    "STS": "STS",
    "Semantic Textual Similarity": "STS",
    "Summarization": "Summarization",
    "BitextMining": "Bitext Mining",
    "Bitext Mining": "Bitext Mining",
    "MultilabelClassification": "Multilabel Classification",
    "Multilabel Classification": "Multilabel Classification",
    "Any-to-Any Retrieval": "Any-to-Any Retrieval",
    "Image Retrieval": "Image Retrieval",
    "Text-to-Image Retrieval": "Text-to-Image Retrieval",
    "Visual Question Answering": "Visual Question Answering",
}


def _first_text(row: dict[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—", "nan", "NaN", "None", "null"}:
        return None
    text = text.removesuffix("%").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "component"


def _rows_from_json(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("rows", "data", "results", "leaderboard"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        return [payload]
    return []


def _decode_rows(raw: bytes) -> list[dict[str, Any]]:
    text = raw.decode("utf-8-sig").strip()
    if not text:
        return []
    if text[0] in "[{":
        return _rows_from_json(json.loads(text))
    return [dict(row) for row in csv.DictReader(StringIO(text))]


def _benchmark_entry(benchmark_id: str, name: str, category: str, score: float,
                     *, metric: str = "score", rank: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "benchmark_id": benchmark_id,
        "name": name,
        "category": category,
        "metric": metric,
        "score": score,
    }
    if rank is not None:
        entry["rank"] = rank
    return entry


def _row_benchmarks(row: dict[str, Any]) -> list[dict[str, Any]]:
    rank_float = _optional_float(_first_text(row, _RANK_KEYS))
    rank = int(rank_float) if rank_float is not None else None
    benchmarks: list[dict[str, Any]] = []

    average = _optional_float(_first_text(row, _SCORE_KEYS))
    if average is not None:
        benchmarks.append(
            _benchmark_entry(
                "mteb_average",
                "MTEB Average",
                "embedding",
                average,
                rank=rank,
            )
        )

    component_payload = row.get("components") or row.get("component_scores") or row.get("task_categories")
    if isinstance(component_payload, dict):
        for label, value in component_payload.items():
            score = _optional_float(value)
            if score is None:
                continue
            name = str(label).strip()
            benchmarks.append(
                _benchmark_entry(
                    f"mteb_{_slug(name)}",
                    f"MTEB {name}",
                    "embedding",
                    score,
                )
            )

    for column, name in _COMPONENT_COLUMNS.items():
        score = _optional_float(row.get(column))
        if score is None:
            continue
        benchmarks.append(
            _benchmark_entry(
                f"mteb_{_slug(name)}",
                f"MTEB {name}",
                "embedding",
                score,
            )
        )

    return benchmarks


class MTEBParser(SourceParser):
    """Parse aggregate MTEB JSON/CSV rows into source-native records."""

    source_id = "mteb"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        raise NotImplementedError(UNSUPPORTED_PARQUET_MESSAGE)

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        for row in _decode_rows(raw):
            model = _first_text(row, _MODEL_KEYS)
            if not model:
                continue
            benchmarks = _row_benchmarks(row)
            if not benchmarks:
                continue

            provider = _first_text(row, _PROVIDER_KEYS)
            if provider is None and "/" in model:
                provider = model.split("/", 1)[0]

            parsed_fields = {
                "model_version": model,
                "benchmark_results": benchmarks,
                "measured_at": _first_text(row, _DATE_KEYS),
            }
            if provider:
                parsed_fields["organization"] = provider

            yield SourceModelRecord(
                source_model_id=model,
                display_name=_first_text(row, ("display_name", "Display Name", "model_name", "Model Name")) or model,
                provider_name=provider,
                raw_record_json=json.dumps(row, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )
