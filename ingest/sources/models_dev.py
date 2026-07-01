from __future__ import annotations

from collections.abc import Iterator
from urllib.request import Request, urlopen

from ingest.base import SourceParser, SourceModelRecord


class ModelsDevParser(SourceParser):
    source_id = "models_dev"
    parser_version = "0.1.0"

    BASE_URL = "https://models.dev/api.json"
    USER_AGENT = "modeldb-ingest/0.1"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(self.BASE_URL, headers={"User-Agent": self.USER_AGENT})
        with urlopen(request, timeout=30) as response:
            return self.BASE_URL, response.read(), {}

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Parse models.dev provider records into source_model_record rows.

        Field extraction contract for M1:
        - Iterate each provider object in api.json.
        - Under each provider, iterate models{} entries.
        - Emit source_model_id as ``provider/model`` using the provider key and model id.
        - Preserve the raw model object in raw_record_json.
        - Extract provider/display identity: model id, name, family.
        - Extract lifecycle fields: release_date, last_updated, knowledge.
        - Extract modality fields: modalities.input, modalities.output.
        - Extract openness fields: open_weights, license.
        - Extract token limits: limit.context, limit.input, limit.output.
        - Extract costs in source units ($/Mtok): cost.input, cost.output,
          cost.cache_read, cost.cache_write.
        - Store extracted values in parsed_fields_json only; do not write canonical model,
          alias, provider_surface, price_component, or capability tables here.
        """
        json = __import__("json")

        def coerce_int(value):
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return None

        def coerce_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def coerce_bool(value):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                normalized = value.strip().lower()
                if normalized == "true":
                    return True
                if normalized == "false":
                    return False
            if value in (0, 1):
                return bool(value)
            return None

        def looks_like_hugging_face_repo(value):
            if not isinstance(value, str):
                return False
            if "://" in value or ":" in value or any(ch.isspace() for ch in value):
                return False
            parts = value.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                return False
            allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
            return all(char in allowed for part in parts for char in part)

        def find_hugging_face_id(value):
            if looks_like_hugging_face_repo(value):
                return value
            if isinstance(value, dict):
                for nested_value in value.values():
                    found = find_hugging_face_id(nested_value)
                    if found is not None:
                        return found
            elif isinstance(value, list):
                for nested_value in value:
                    found = find_hugging_face_id(nested_value)
                    if found is not None:
                        return found
            return None

        data = json.loads(raw)
        if not isinstance(data, dict):
            return

        explicit_hf_keys = (
            "hugging_face_id",
            "huggingface_id",
            "hugging_face",
            "huggingface",
            "hf_id",
            "hf_repo",
            "hf_repo_id",
            "hf_model",
            "hf_model_id",
        )

        for provider_id, provider in data.items():
            if not provider_id or not isinstance(provider, dict):
                continue
            models = provider.get("models") or {}
            if not isinstance(models, dict):
                continue

            for model_id, model in models.items():
                if not model_id or not isinstance(model, dict):
                    continue

                fields = {
                    "provider_id": provider_id,
                    "model_id": model_id,
                }

                for source_key, field_key in (
                    ("name", "name"),
                    ("family", "family"),
                    ("release_date", "release_date"),
                    ("last_updated", "last_updated"),
                    ("knowledge", "knowledge"),
                    ("license", "license"),
                ):
                    value = model.get(source_key)
                    if value is not None:
                        fields[field_key] = value

                modalities = model.get("modalities") or {}
                if isinstance(modalities, dict):
                    input_modalities = modalities.get("input")
                    if input_modalities is not None:
                        fields["input_modalities"] = input_modalities
                    output_modalities = modalities.get("output")
                    if output_modalities is not None:
                        fields["output_modalities"] = output_modalities

                open_weights = coerce_bool(model.get("open_weights"))
                if open_weights is not None:
                    fields["open_weights"] = open_weights

                limits = model.get("limit") or {}
                if isinstance(limits, dict):
                    for source_key, field_key in (
                        ("context", "context_limit"),
                        ("input", "input_limit"),
                        ("output", "output_limit"),
                    ):
                        value = coerce_int(limits.get(source_key))
                        if value is not None:
                            fields[field_key] = value

                costs = model.get("cost") or {}
                if isinstance(costs, dict):
                    for source_key, field_key in (
                        ("input", "cost_input"),
                        ("output", "cost_output"),
                        ("cache_read", "cost_cache_read"),
                        ("cache_write", "cost_cache_write"),
                    ):
                        value = coerce_float(costs.get(source_key))
                        if value is not None:
                            fields[field_key] = value

                hugging_face_id = None
                for key in explicit_hf_keys:
                    hugging_face_id = find_hugging_face_id(model.get(key))
                    if hugging_face_id is not None:
                        break
                if hugging_face_id is None:
                    hugging_face_id = find_hugging_face_id(model.get("weights"))
                if hugging_face_id is not None:
                    fields["hugging_face_id"] = hugging_face_id

                yield SourceModelRecord(
                    source_model_id=f"{provider_id}/{model_id}",
                    display_name=model.get("name"),
                    provider_name=provider_id,
                    raw_record_json=json.dumps(model, sort_keys=True),
                    parsed_fields_json=json.dumps(fields, sort_keys=True),
                )
