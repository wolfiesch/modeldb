"""LiveBench source parser stub."""
from __future__ import annotations

from collections.abc import Iterator

from ingest.base import SourceModelRecord, SourceParser


class LiveBench(SourceParser):
    """Parser stub for LiveBench model_judgment dataset snapshots."""

    source_id = "livebench"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): Fetch Hugging Face dataset parquet files from
        # https://huggingface.co/datasets/livebench/model_judgment and compare HF
        # lastModified against upstream release metadata for freshness.
        raise NotImplementedError("M3: needs Hugging Face parquet dataset fetch")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract model_judgment parquet fields question_id, task, model, score,
        turn, tstamp, and category. Aggregate to category-level and global LiveBench
        benchmark_result source rows.
        """
        # TODO(M3): Decode parquet and aggregate per model/category/global scores.
        yield from ()
