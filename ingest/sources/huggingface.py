"""Hugging Face Hub source parser for supplied per-repo API payloads."""
from __future__ import annotations

import json

from collections.abc import Iterator
from typing import Any

from ingest.base import SourceModelRecord, SourceParser


class HuggingFaceParser(SourceParser):
    """Parse a bounded JSON array of per-model Hugging Face API responses.

    The parser stays DB-pure: callers decide which known repo ids to fetch and
    provide a JSON array of ``{repo_id, status, body}`` objects. This avoids any
    full Hub crawl from parser code.
    """

    source_id = "huggingface"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        raise NotImplementedError("Hugging Face fetch needs caller-supplied known repo ids")

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            return

        for item in payload:
            if not isinstance(item, dict):
                continue

            repo_id = item.get("repo_id")
            if not isinstance(repo_id, str) or not repo_id.strip():
                continue
            repo_id = repo_id.strip()

            status = item.get("status")
            body = item.get("body")
            if not isinstance(body, dict):
                body = {}

            card_data = body.get("cardData")
            if not isinstance(card_data, dict):
                card_data = {}

            safetensors = body.get("safetensors")
            if not isinstance(safetensors, dict):
                safetensors = {}

            fields: dict[str, Any] = {"repo_id": repo_id, "status": status}
            self._add_if_present(fields, "modelId", body.get("modelId"))
            self._add_if_present(fields, "id", body.get("id"))
            self._add_if_present(fields, "author", body.get("author"))
            self._add_if_present(fields, "sha", body.get("sha"))
            self._add_if_present(fields, "lastModified", body.get("lastModified"))
            self._add_if_present(fields, "gated", body.get("gated"))
            self._add_if_present(fields, "tags", body.get("tags"))
            self._add_if_present(fields, "pipeline_tag", body.get("pipeline_tag"))
            self._add_if_present(fields, "library_name", body.get("library_name"))
            self._add_if_present(fields, "license", card_data.get("license"))
            self._add_if_present(fields, "cardData", card_data)
            self._add_if_present(fields, "safetensors", safetensors)
            self._add_if_present(fields, "safetensors_total", safetensors.get("total"))
            self._add_if_present(fields, "safetensors_parameters", safetensors.get("parameters"))
            self._add_if_present(fields, "siblings", self._siblings(body.get("siblings")))
            self._add_if_present(fields, "downloads", body.get("downloads"))
            self._add_if_present(fields, "likes", body.get("likes"))

            raw_record = {"repo_id": repo_id, "status": status, "body": body}
            display_name = body.get("modelId") or body.get("id") or repo_id

            yield SourceModelRecord(
                source_model_id=repo_id,
                display_name=str(display_name),
                provider_name="huggingface",
                raw_record_json=json.dumps(raw_record, sort_keys=True),
                parsed_fields_json=json.dumps(fields, sort_keys=True),
            )

    @staticmethod
    def _add_if_present(fields: dict[str, Any], key: str, value: Any) -> None:
        if value is not None:
            fields[key] = value

    @staticmethod
    def _siblings(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []

        siblings: list[dict[str, Any]] = []
        for sibling in value:
            if not isinstance(sibling, dict):
                continue
            normalized: dict[str, Any] = {}
            for key in ("rfilename", "filename", "size", "sizeBytes", "blob_id"):
                if sibling.get(key) is not None:
                    normalized[key] = sibling[key]
            lfs = sibling.get("lfs")
            if isinstance(lfs, dict):
                normalized["lfs"] = {
                    key: lfs[key]
                    for key in ("oid", "size", "pointerSize")
                    if lfs.get(key) is not None
                }
            if normalized:
                siblings.append(normalized)
        return siblings


HuggingFace = HuggingFaceParser
