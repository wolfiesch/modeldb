"""BigCodeBench leaderboard source parser."""
from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from ingest.base import SourceModelRecord, SourceParser


DATASET = "bigcode/bigcodebench-results"
CONFIG = "default"
SPLIT = "train"
PAGE_LENGTH = 100
BASE_ROWS_URL = "https://datasets-server.huggingface.co/rows"
DATASET_URL = (
    "https://datasets-server.huggingface.co/rows?"
    "dataset=bigcode%2Fbigcodebench-results&config=default&split=train&offset=0&length=100"
)
USER_AGENT = "modeldb-ingest/0.1"


class BigCodeBenchParser(SourceParser):
    """Parse Hugging Face datasets-server rows for BigCodeBench results."""

    source_id = "bigcodebench"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        rows: list[Mapping[str, Any]] = []
        total: int | None = None
        first_url: str | None = None
        first_headers: Any = None
        offset = 0

        while total is None or offset < total:
            url = _rows_url(offset)
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read())
                if first_url is None:
                    first_url = response.geturl()
                    first_headers = response.headers

            page_rows = payload.get("rows") if isinstance(payload, Mapping) else None
            if not isinstance(page_rows, list):
                page_rows = []
            rows.extend(item for item in page_rows if isinstance(item, Mapping))

            if total is None:
                total_value = payload.get("num_rows_total") if isinstance(payload, Mapping) else None
                total = int(total_value) if total_value is not None else len(page_rows)

            if not page_rows:
                break
            offset += PAGE_LENGTH

        raw = json.dumps(
            {"rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        headers = first_headers
        return first_url or DATASET_URL, raw, {
            "etag": headers.get("ETag") if headers is not None else None,
            "last_modified": headers.get("Last-Modified") if headers is not None else None,
        }

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        rows = payload.get("rows") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            return

        for item in rows:
            if not isinstance(item, Mapping):
                continue
            row = item.get("row")
            if not isinstance(row, Mapping):
                continue

            model_name = str(row.get("model") or "").strip()
            if not model_name:
                continue

            link = _optional_string(row.get("link"))
            date = _optional_string(row.get("date"))
            prefill = row.get("prefill")
            parsed_fields: dict[str, Any] = {
                "link": link,
                "hf_repo_id": _hf_repo_id(link),
                "moe": row.get("moe"),
                "size": row.get("size"),
                "active_parameters": row.get("act_param"),
                "model_type": row.get("type"),
                "prefill": prefill,
                "date": date,
                "benchmark_results": _benchmark_results(row, date, prefill),
            }

            yield SourceModelRecord(
                source_model_id=model_name,
                display_name=model_name,
                provider_name=_provider_from_hf_link(link),
                raw_record_json=json.dumps(item, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )


BigCodeBench = BigCodeBenchParser


def _rows_url(offset: int) -> str:
    query = urlencode(
        {
            "dataset": DATASET,
            "config": CONFIG,
            "split": SPLIT,
            "offset": offset,
            "length": PAGE_LENGTH,
        }
    )
    return f"{BASE_ROWS_URL}?{query}"


def _benchmark_results(row: Mapping[str, Any], date: str | None, prefill: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for field, benchmark_id, name in (
        ("complete", "bigcodebench_complete", "BigCodeBench Complete"),
        ("instruct", "bigcodebench_instruct", "BigCodeBench Instruct"),
    ):
        score = _optional_float(row.get(field))
        if score is None:
            continue
        results.append(
            {
                "benchmark_id": benchmark_id,
                "name": name,
                "category": "coding",
                "metric": "pass_rate",
                "score": score,
                "measured_at": date,
                "date": date,
                "source_url": DATASET_URL,
                "eval_condition": {
                    "split": SPLIT,
                    "prefill": prefill,
                },
            }
        )
    return results


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


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _hf_repo_id(link: str | None) -> str | None:
    parts = _hf_path_parts(link)
    if len(parts) < 2:
        return None
    return "/".join(parts[:2])


def _provider_from_hf_link(link: str | None) -> str | None:
    parts = _hf_path_parts(link)
    if not parts:
        return None
    return parts[0]


def _hf_path_parts(link: str | None) -> list[str]:
    if not link:
        return []
    parsed = urlparse(link)
    if parsed.scheme != "https" or parsed.netloc.lower() != "huggingface.co":
        return []
    return [part for part in parsed.path.split("/") if part]
