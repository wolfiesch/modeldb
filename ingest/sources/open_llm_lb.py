"""Archived Hugging Face Open LLM Leaderboard source parser stub."""
from __future__ import annotations

from collections.abc import Iterator

from ingest.base import SourceModelRecord, SourceParser


class OpenLLMLeaderboard(SourceParser):
    """Parser stub for the frozen Open LLM Leaderboard archive."""

    source_id = "open_llm_lb"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): Fetch archived Hugging Face dataset contents/parquet from
        # https://huggingface.co/api/datasets/open-llm-leaderboard/contents.
        # Treat as FROZEN historical data, not a live leaderboard.
        raise NotImplementedError("M3: needs Hugging Face archived parquet fetch")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract contents parquet fields eval_name, Model, fullname, Model sha,
        Average ⬆️, Hub License, #Params (B), IFEval, BBH, MATH Lvl 5, GPQA, MUSR,
        MMLU-PRO, Submission Date, and Base Model. Treat this source as a FROZEN archive.
        """
        # TODO(M3): Decode archived parquet rows into historical benchmark_result records.
        yield from ()
