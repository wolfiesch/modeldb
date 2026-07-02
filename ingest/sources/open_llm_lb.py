"""Archived Hugging Face Open LLM Leaderboard source parser."""
from __future__ import annotations

import csv
import io
import json
import urllib.request

from collections.abc import Iterator, Mapping
from typing import Any

from ingest.base import SourceModelRecord, SourceParser


CONTENTS_API_URL = "https://huggingface.co/api/datasets/open-llm-leaderboard/contents"
DATASET_URL = "https://huggingface.co/datasets/open-llm-leaderboard/contents"

COMPONENT_FIELDS = {
    "IFEval": "ifeval",
    "BBH": "bbh",
    "MATH Lvl 5": "math_l5",
    "GPQA": "gpqa",
    "MUSR": "musr",
    "MMLU-PRO": "mmlu_pro",
}


class OpenLLMLBParser(SourceParser):
    """Parser for supplied JSON/CSV exports of the frozen Open LLM Leaderboard.

    The public Hugging Face archive currently exposes its rows as parquet. To keep
    this source stdlib-only, live fetch only accepts future JSON/CSV siblings and
    otherwise asks callers to supply a pre-converted JSON/CSV array to ``parse``.
    """

    source_id = "open_llm_lb"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        with urllib.request.urlopen(CONTENTS_API_URL, timeout=30) as response:
            metadata = json.loads(response.read())
            etag = response.headers.get("etag")
            last_modified = response.headers.get("last-modified")

        for sibling in metadata.get("siblings") or ():
            if not isinstance(sibling, Mapping):
                continue
            filename = str(sibling.get("rfilename") or "")
            if not filename.lower().endswith((".json", ".csv")):
                continue
            url = f"{DATASET_URL}/resolve/main/{filename}"
            with urllib.request.urlopen(url, timeout=30) as response:
                return (
                    url,
                    response.read(),
                    {
                        "etag": response.headers.get("etag") or etag,
                        "last_modified": response.headers.get("last-modified") or last_modified,
                    },
                )

        raise NotImplementedError(
            "Open LLM Leaderboard archive is parquet-only; supply JSON or CSV rows to parse"
        )

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract Open LLM Leaderboard rows from caller-supplied JSON or CSV bytes."""
        for row in _iter_rows(raw):
            fields = _parsed_fields(row)
            source_model_id = fields.get("fullname") or fields.get("model_name")
            if not isinstance(source_model_id, str) or not source_model_id.strip():
                continue
            source_model_id = source_model_id.strip()
            fields["source_model_id"] = source_model_id

            display_name = fields.get("model_name") or source_model_id
            provider_name = source_model_id.split("/", 1)[0] if "/" in source_model_id else None
            raw_record_json = json.dumps(row, sort_keys=True)

            yield SourceModelRecord(
                source_model_id=source_model_id,
                display_name=str(display_name),
                provider_name=provider_name,
                raw_record_json=raw_record_json,
                parsed_fields_json=json.dumps(fields, sort_keys=True),
            )


def _iter_rows(raw: bytes) -> Iterator[dict[str, Any]]:
    text = raw.decode("utf-8-sig")
    stripped = text.lstrip()
    if not stripped:
        return

    if stripped[0] in "[{":
        payload = json.loads(text)
        rows = payload
        if isinstance(payload, Mapping):
            for key in ("rows", "data", "records"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    rows = candidate
                    break
        if not isinstance(rows, list):
            return
        for item in rows:
            if isinstance(item, Mapping):
                yield dict(item)
        return

    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        yield dict(row)


def _parsed_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    _copy_first(fields, row, "eval_name", ("eval_name",))
    _copy_first(fields, row, "model_name", ("Model", "model", "model_name"))
    _copy_first(fields, row, "fullname", ("fullname", "Fullname", "repo_id"))
    _copy_first(fields, row, "model_sha", ("Model sha", "model_sha", "sha"))
    _copy_first(fields, row, "license", ("Hub License", "license"))
    _copy_float(fields, row, "params_b", ("#Params (B)", "params_b", "parameters_b"))
    _copy_first(fields, row, "submission_date", ("Submission Date", "submission_date"))
    _copy_first(fields, row, "upload_to_hub_date", ("Upload To Hub Date", "upload_to_hub_date"))
    _copy_first(fields, row, "base_model", ("Base Model", "base_model"))
    _copy_float(fields, row, "average_score", ("Average ⬆️", "Average", "average_score"))

    component_scores: dict[str, float] = {}
    for source_key, field_key in COMPONENT_FIELDS.items():
        score = _optional_float(_first_present(row, (source_key, field_key)))
        if score is not None:
            component_scores[field_key] = score
    if component_scores:
        fields["component_scores"] = component_scores

    return fields


def _copy_first(
    fields: dict[str, Any],
    row: Mapping[str, Any],
    target: str,
    keys: tuple[str, ...],
) -> None:
    value = _first_present(row, keys)
    if value is not None:
        fields[target] = value


def _copy_float(
    fields: dict[str, Any],
    row: Mapping[str, Any],
    target: str,
    keys: tuple[str, ...],
) -> None:
    value = _optional_float(_first_present(row, keys))
    if value is not None:
        fields[target] = value


def _first_present(row: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


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


OpenLLMLeaderboard = OpenLLMLBParser
