from __future__ import annotations

import csv
import io
import json
import urllib.request
import zipfile
from collections.abc import Iterator

from ingest.base import SourceParser, SourceModelRecord


class EpochParser(SourceParser):
    source_id = "epoch"
    parser_version = "0.1.0"

    BASE_URL = "https://epoch.ai/data/benchmark_data.zip"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = urllib.request.Request(
            self.BASE_URL,
            headers={"User-Agent": "modeldb-ingest/0.1 (+https://epoch.ai/data)"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return (self.BASE_URL, response.read(), {})

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Parse Epoch benchmark CSV rows into benchmark_result-ready records.

        Field extraction contract for M2:
        - Read the ZIP archive and process these CSVs: gpqa_diamond, math_level_5,
          mmlu_external, swe_bench_verified, aider_polyglot_external,
          live_bench_external, frontiermath, epoch_capabilities_index.
        - For each CSV row, preserve the raw row in raw_record_json.
        - Extract model identity fields: Model version, Organization, Release date.
        - Extract the benchmark-specific score column; the score column name varies by CSV.
        - Extract uncertainty/provenance fields: stderr, Source, Source link.
        - Emit source_model_id from the model/version plus benchmark name so duplicate model
          rows across benchmarks stay distinct at source_model_record granularity.
        - These records feed benchmark and benchmark_result rows after canonical resolution;
          parsers must not create canonical model ids or benchmark_result rows directly.
        """
        benchmark_ids = {
            "gpqa_diamond.csv": "gpqa_diamond",
            "math_level_5.csv": "math_level_5",
            "mmlu_external.csv": "mmlu",
            "swe_bench_verified.csv": "swe_bench_verified",
            "aider_polyglot_external.csv": "aider_polyglot",
            "live_bench_external.csv": "livebench",
            "frontiermath.csv": "frontiermath",
            "epoch_capabilities_index.csv": "epoch_capabilities_index",
        }
        members_by_basename = {}

        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for member in archive.namelist():
                basename = member.rsplit("/", 1)[-1]
                if basename in benchmark_ids and basename not in members_by_basename:
                    members_by_basename[basename] = member

            for basename, benchmark_id in benchmark_ids.items():
                member = members_by_basename.get(basename)
                if member is None:
                    continue

                with archive.open(member) as csv_file:
                    text_file = io.TextIOWrapper(csv_file, encoding="utf-8-sig", newline="")
                    rows = list(csv.DictReader(text_file))
                if not rows:
                    continue

                headers = list(rows[0].keys())
                identity_column = self._identity_column(headers)
                score_column = self._score_column(headers, rows, identity_column)
                if not identity_column or not score_column:
                    continue

                for row in rows:
                    model_version = (row.get(identity_column) or "").strip()
                    if not model_version:
                        continue

                    score = self._parse_float(row.get(score_column))
                    if score is None:
                        continue

                    stderr = self._parse_float(row.get("stderr"))
                    organization = row.get("Organization")
                    fields = {
                        "benchmark_id": benchmark_id,
                        "model_version": model_version,
                        "score": score,
                        "score_column": score_column,
                        "organization": organization,
                        "release_date": row.get("Release date"),
                        "stderr": stderr,
                        "source": row.get("Source"),
                        "source_link": row.get("Source link"),
                    }
                    yield SourceModelRecord(
                        source_model_id=f"{benchmark_id}::{model_version}",
                        display_name=model_version,
                        provider_name=organization or None,
                        raw_record_json=json.dumps(row, sort_keys=True),
                        parsed_fields_json=json.dumps(fields, sort_keys=True),
                    )

    @staticmethod
    def _identity_column(headers: list[str | None]) -> str | None:
        lower_headers = {
            header.casefold(): header
            for header in headers
            if header is not None
        }
        return lower_headers.get("model version") or lower_headers.get("model") or next(
            (header for header in headers if header),
            None,
        )

    @classmethod
    def _score_column(
        cls,
        headers: list[str | None],
        rows: list[dict[str | None, str | None]],
        identity_column: str | None,
    ) -> str | None:
        lower_headers = {
            header.casefold(): header
            for header in headers
            if header is not None
        }
        for preferred in (
            "Best score",
            "mean_score",
            "Percent correct",
            "EM",
            "Global average",
            "score",
            "accuracy",
            "Score",
        ):
            header = lower_headers.get(preferred.casefold())
            if header is not None:
                return header

        row_count = len(rows)
        for header in headers:
            if not header or header == identity_column:
                continue
            parsed_count = sum(
                1
                for row in rows
                if cls._parse_float(row.get(header)) is not None
            )
            if parsed_count > row_count / 2:
                return header
        return None

    @staticmethod
    def _parse_float(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, int | float):
            return float(value)

        text = str(value).strip()
        if not text:
            return None
        if text.endswith("%"):
            text = text[:-1].strip()
        text = text.replace(",", "")
        try:
            return float(text)
        except ValueError:
            return None
