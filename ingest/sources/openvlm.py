"""OpenVLM leaderboard source parser."""
from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.request import Request, urlopen

from ingest.base import SourceModelRecord, SourceParser


SOURCE_URL = "http://opencompass.openxlab.space/assets/OpenVLM.json"
USER_AGENT = "modeldb-ingest/0.1"

_BENCHMARKS = {
    "MMMU_VAL": {
        "benchmark_id": "openvlm_mmmu_val",
        "name": "OpenVLM MMMU Validation",
        "score_key": "Overall",
        "split": "VAL",
    },
    "MathVista": {
        "benchmark_id": "openvlm_mathvista_mini",
        "name": "OpenVLM MathVista Mini",
        "score_key": "Overall",
        "split": "MINI",
    },
    "MMBench_TEST_EN_V11": {
        "benchmark_id": "openvlm_mmbench_en_v11",
        "name": "OpenVLM MMBench Test English v1.1",
        "split": "TEST_EN_V11",
        "score_key": "Overall",
    },
    "OCRBench": {
        "benchmark_id": "openvlm_ocrbench",
        "name": "OpenVLM OCRBench",
        "score_key": "Final Score",
        "split": "Overall",
    },
    "MMVet": {
        "benchmark_id": "openvlm_mmvet",
        "name": "OpenVLM MMVet",
        "split": "Overall",
        "score_key": "Overall",
    },
}


class OpenVLMParser(SourceParser):
    """Parse OpenVLM aggregate JSON rows into source-native model records."""

    source_id = "openvlm"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            headers = response.headers
            return response.geturl(), raw, {
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
            }

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            return

        source_time = _text(payload.get("time"))
        results = payload.get("results")
        if not isinstance(results, Mapping):
            return

        for display_key, record in results.items():
            if not isinstance(record, Mapping):
                continue

            meta_value = record.get("META")
            meta = meta_value if isinstance(meta_value, Mapping) else {}
            source_model_id = _text(meta.get("dir_name")) or str(display_key).strip()
            if not source_model_id:
                continue

            display_name, method_url = _method(meta.get("Method"))
            display_name = display_name or str(display_key).strip() or source_model_id
            provider_name = _text(meta.get("Org"))
            measured_at = _text(meta.get("Time")) or source_time
            benchmark_results = _benchmark_results(record, measured_at)

            parsed_fields = {
                "source": self.source_id,
                "source_time": source_time,
                "verified": _text(meta.get("Verified")),
                "open_source": _text(meta.get("OpenSource")),
                "method_url": method_url,
                "parameters": _text(meta.get("Parameters")),
                "language_model": _text(meta.get("Language Model")),
                "vision_model": _text(meta.get("Vision Model")),
                "benchmark_results": benchmark_results,
            }

            yield SourceModelRecord(
                source_model_id=source_model_id,
                display_name=display_name,
                provider_name=provider_name,
                raw_record_json=json.dumps(record, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )


def _benchmark_results(record: Mapping[str, Any], measured_at: str | None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for source_block, metadata in _BENCHMARKS.items():
        block = record.get(source_block)
        if not isinstance(block, Mapping):
            continue
        score_key = str(metadata.get("score_key") or "Overall")
        score = _optional_float(block.get(score_key))
        if score is None:
            continue
        results.append(
            {
                "benchmark_id": metadata["benchmark_id"],
                "name": metadata["name"],
                "category": "multimodal",
                "metric": "score",
                "score": score,
                "measured_at": measured_at,
                "date": measured_at,
                "source_url": SOURCE_URL,
                "eval_condition": {
                    "source_benchmark": source_block,
                    "source_metric": score_key,
                    "split": metadata["split"],
                },
            }
        )
    return results


def _method(value: Any) -> tuple[str | None, str | None]:
    if isinstance(value, list):
        name = _text(value[0]) if value else None
        url = _text(value[1]) if len(value) > 1 else None
        return name, url
    return _text(value), None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().removesuffix("%").replace(",", "")
    if not text or text in {"-", "—", "N/A", "NA", "nan", "NaN", "None", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


OpenVLM = OpenVLMParser
