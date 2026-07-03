"""OMP local speedtest source parser."""
from __future__ import annotations

import json
import math
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ingest.base import SourceModelRecord, SourceParser


class OMPSpeedtestParser(SourceParser):
    source_id = "omp_speedtest"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        input_path = os.environ.get("OMP_SPEEDTEST_INPUT")
        if not input_path:
            raise NotImplementedError(
                "OMP speedtest fetch requires OMP_SPEEDTEST_INPUT pointing at a JSON payload"
            )
        path = Path(input_path).expanduser()
        raw = path.read_bytes()
        return (f"file://{path.name}", raw, {})

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        del snapshot_id
        payload = json.loads(raw.decode("utf-8"))
        configs = {
            config.get("ompSelector"): config
            for config in payload.get("models", [])
            if isinstance(config, dict) and config.get("ompSelector")
        }
        records = payload.get("speedtest", {}).get("records", [])
        if not isinstance(records, list):
            return

        for record in records:
            if not isinstance(record, dict):
                continue
            if record.get("status") != "ok":
                continue
            tps = record.get("visibleTokensPerSecond")
            if not _positive_finite(tps):
                continue
            config = configs.get(record.get("model"))
            if not config:
                continue

            parsed_fields = _compact(
                {
                    "runId": payload.get("runId"),
                    "canonicalSlug": config.get("canonicalSlug"),
                    "label": config.get("label"),
                    "ompSelector": config.get("ompSelector"),
                    "providerLabel": config.get("providerLabel"),
                    "timestamp": record.get("timestamp"),
                    "mode": record.get("mode"),
                    "run": record.get("run"),
                    "durationMs": record.get("durationMs"),
                    "visibleTokens": record.get("visibleTokens"),
                    "visibleTokensPerSecond": tps,
                    "visibleChars": record.get("visibleChars"),
                    "visibleCharsPerSecond": record.get("visibleCharsPerSecond"),
                    "tokenizer": record.get("tokenizer"),
                    "prompt": payload.get("prompt"),
                    "runs": payload.get("runs"),
                    "timeoutSeconds": payload.get("timeoutSeconds"),
                    "artifactPath": payload.get("artifactPath"),
                    "sourceHash": payload.get("sourceHash"),
                    "buildMode": payload.get("buildMode"),
                    "scenario": payload.get("scenario"),
                }
            )
            yield SourceModelRecord(
                source_model_id=str(config["ompSelector"]),
                display_name=config.get("label"),
                provider_name=config.get("providerLabel"),
                raw_record_json=json.dumps(record, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )


def _positive_finite(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _compact(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
