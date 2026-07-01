"""Artificial Analysis source parser stub."""
from __future__ import annotations

from collections.abc import Iterator

from ingest.base import SourceModelRecord, SourceParser


class ArtificialAnalysis(SourceParser):
    """Parser stub for the Artificial Analysis LLM models API."""

    source_id = "artificialanalysis"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): Read ARTIFICIALANALYSIS_API_KEY and GET with header
        # x-api-key: <key>. Endpoint: https://artificialanalysis.ai/api/v2/data/llms/models
        # Free plan is documented at 1000 requests/day; respect caching and cadence.
        raise NotImplementedError("M3: needs ARTIFICIALANALYSIS_API_KEY")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract id (stable UUID), slug, name, model_creator.{id,slug,name},
        evaluations.{artificial_analysis_intelligence_index,coding_index,math_index,
        mmlu_pro,gpqa,hle,livecodebench,aime,math_500}, pricing.{price_1m_input_tokens,
        price_1m_output_tokens,price_1m_blended_3_to_1},
        median_output_tokens_per_second, and median_time_to_first_token_seconds.
        Context window should be filled only from the RSC fallback, not this API payload.
        """
        # TODO(M3): Normalize model rows and benchmark/price fields.
        yield from ()
