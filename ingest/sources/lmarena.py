from __future__ import annotations

import io
import json
import urllib.request
from collections.abc import Iterator

import pandas as pd
import pyarrow.parquet as pq

from ingest.base import SourceParser, SourceModelRecord


class LMArenaParser(SourceParser):
    source_id = "lmarena"
    parser_version = "0.1.0"

    BASE_URL = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset"
    FULL_SPLIT_URL = (
        "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/"
        "text/full-00000-of-00001.parquet"
    )

    @staticmethod
    def _jsonable(value):
        if pd.isna(value):
            return None
        if hasattr(value, "item"):
            value = value.item()
        return value

    @classmethod
    def _row_json(cls, row: dict) -> str:
        return json.dumps({str(key): cls._jsonable(value) for key, value in row.items()}, sort_keys=True)

    def fetch(self) -> tuple[str, bytes, dict]:
        request = urllib.request.Request(
            self.FULL_SPLIT_URL,
            headers={"User-Agent": "modeldb-lmarena-parser/0.1.0"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return self.FULL_SPLIT_URL, response.read(), {}

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        df = pq.read_table(io.BytesIO(raw)).to_pandas()
        df = df[df["category"].isin({"overall", "coding"})]

        for row in df.to_dict(orient="records"):
            model_name = row.get("model_name")
            rating = row.get("rating")
            if pd.isna(model_name) or pd.isna(rating):
                continue

            try:
                category = str(row.get("category"))
                publish_date = str(row.get("leaderboard_publish_date"))
                fields = {
                    "model_name": str(model_name),
                    "organization": str(row.get("organization")),
                    "category": category,
                    "rating": float(rating),
                    "rating_lower": float(row.get("rating_lower")),
                    "rating_upper": float(row.get("rating_upper")),
                    "vote_count": int(row.get("vote_count")),
                    "rank": int(row.get("rank")),
                    "publish_date": publish_date,
                    "license": str(row.get("license")),
                }
            except (TypeError, ValueError):
                continue

            yield SourceModelRecord(
                source_model_id=f"{category}::{model_name}::{publish_date}",
                display_name=str(model_name),
                provider_name=fields["organization"],
                raw_record_json=self._row_json(row),
                parsed_fields_json=json.dumps(fields, sort_keys=True),
            )
