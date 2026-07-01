"""Hugging Face Hub source parser stub."""
from __future__ import annotations

from collections.abc import Iterator

from ingest.base import SourceModelRecord, SourceParser


class HuggingFace(SourceParser):
    """Parser stub for per-model Hugging Face Hub API lookups."""

    source_id = "huggingface"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        # TODO(M3): Pull only known repository ids via https://huggingface.co/api/models/{repo_id}
        # rather than full-crawling the Hub; anonymous limits are around 500 requests/5 minutes.
        raise NotImplementedError("M3: needs known Hugging Face repo ids")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """For each known repo id, extract modelId, author, sha, createdAt,
        lastModified, gated, tags, pipeline_tag, library_name,
        cardData.{license,base_model}, safetensors.total/parameters, downloads,
        and likes. Emit these as pre-resolution source records and feed model_artifact rows
        in the storage layer.
        """
        # TODO(M3): Normalize Hub metadata for model_artifact ingestion.
        yield from ()
