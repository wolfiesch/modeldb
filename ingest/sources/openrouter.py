from __future__ import annotations

import json

from collections.abc import Iterator
from urllib.request import Request, urlopen

from ingest.base import SourceParser, SourceModelRecord


class OpenRouterParser(SourceParser):
    source_id = "openrouter"
    parser_version = "0.1.0"

    BASE_URL = "https://openrouter.ai/api/v1/models"
    USER_AGENT = "modeldb-ingest/0.1"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(self.BASE_URL, headers={"User-Agent": self.USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return self.BASE_URL, response.read(), {}

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Parse OpenRouter model catalog records into source_model_record rows.

        Field extraction contract for M1:
        - Iterate response data[] records.
        - Emit source_model_id from data[].id.
        - Preserve the raw data[] object in raw_record_json.
        - Extract identity/bridge fields: id, canonical_slug, hugging_face_id, name.
        - Extract lifecycle/capacity fields: created, context_length.
        - Extract pricing fields in source units (per-token strings where supplied):
          pricing.prompt, pricing.completion, pricing.request, pricing.image.
        - Extract architecture fields: architecture.modality,
          architecture.input_modalities, architecture.output_modalities,
          architecture.tokenizer.
        - Extract top-provider limits: top_provider.context_length,
          top_provider.max_completion_tokens.
        - Extract supported_parameters exactly as reported.
        - Store extracted values in parsed_fields_json only; later resolver/store steps create
          aliases, provider_surface rows, price_component rows, artifacts, and capabilities.
        """
        payload = json.loads(raw)
        data = payload.get("data") if isinstance(payload, dict) else []

        for record in data or []:
            if not isinstance(record, dict):
                continue

            source_model_id = record.get("id")
            if source_model_id is None:
                continue
            source_model_id = str(source_model_id)
            if not source_model_id:
                continue

            fields = {}

            def add_if_present(key: str, value: object) -> None:
                if value is not None:
                    fields[key] = value

            def add_int(key: str, value: object) -> None:
                if value is None:
                    return
                try:
                    fields[key] = int(value)
                except (TypeError, ValueError):
                    return

            def add_float(key: str, value: object) -> None:
                if value is None:
                    return
                try:
                    fields[key] = float(value)
                except (TypeError, ValueError):
                    return

            pricing = record.get("pricing") or {}
            architecture = record.get("architecture") or {}
            top_provider = record.get("top_provider") or {}
            if not isinstance(pricing, dict):
                pricing = {}
            if not isinstance(architecture, dict):
                architecture = {}
            if not isinstance(top_provider, dict):
                top_provider = {}

            add_if_present("id", source_model_id)
            add_if_present("canonical_slug", record.get("canonical_slug"))
            add_if_present("hugging_face_id", record.get("hugging_face_id"))
            add_if_present("name", record.get("name"))
            add_int("created", record.get("created"))
            add_int("context_length", record.get("context_length"))
            add_float("price_prompt", pricing.get("prompt"))
            add_float("price_completion", pricing.get("completion"))
            add_float("price_request", pricing.get("request"))
            add_float("price_image", pricing.get("image"))
            add_if_present("modality", architecture.get("modality"))
            add_if_present("input_modalities", architecture.get("input_modalities"))
            add_if_present("output_modalities", architecture.get("output_modalities"))
            add_if_present("tokenizer", architecture.get("tokenizer"))
            add_int("top_provider_context_length", top_provider.get("context_length"))
            add_int(
                "top_provider_max_completion_tokens",
                top_provider.get("max_completion_tokens"),
            )
            add_if_present("supported_parameters", record.get("supported_parameters"))

            yield SourceModelRecord(
                source_model_id=source_model_id,
                display_name=record.get("name"),
                provider_name="openrouter",
                raw_record_json=json.dumps(record, sort_keys=True),
                parsed_fields_json=json.dumps(fields, sort_keys=True),
            )
