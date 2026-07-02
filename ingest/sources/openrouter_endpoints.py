from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator
from typing import Any

from ingest.base import SourceModelRecord, SourceParser


class OpenRouterEndpointsParser(SourceParser):
    """DB-pure parser for pre-fetched OpenRouter /endpoints payload arrays.

    Endpoint crawling depends on known OpenRouter IDs in SQLite, so the live crawler
    lives in store.openrouter_endpoints. This parser only normalizes a supplied JSON
    array of {model_id, url, status, body} payloads when a caller has already fetched
    those bodies.
    """

    source_id = "openrouter_endpoints"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        raise NotImplementedError(
            "OpenRouter endpoint crawling is DB-scoped; use "
            "store.openrouter_endpoints.promote_openrouter_endpoints."
        )

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        payload = json.loads(raw)
        if not isinstance(payload, list):
            return

        for fetched in payload:
            if not isinstance(fetched, dict):
                continue
            router_model_id = fetched.get("model_id")
            if not router_model_id:
                continue
            router_model_id = str(router_model_id)
            status = _coerce_int(fetched.get("status"))
            body = fetched.get("body")
            body_payload = _loads_body(body)
            for index, endpoint in enumerate(_extract_endpoints(body_payload)):
                fields = _parsed_fields(
                    router_model_id=router_model_id,
                    url=fetched.get("url"),
                    http_status=status,
                    endpoint=endpoint,
                )
                provider_name = endpoint.get("provider_name")
                source_model_id = f"{router_model_id}::{fields.get('provider_id') or 'unknown'}::{index}"
                yield SourceModelRecord(
                    source_model_id=source_model_id,
                    display_name=endpoint.get("model_name") or endpoint.get("name"),
                    provider_name=str(provider_name) if provider_name else None,
                    raw_record_json=json.dumps(endpoint, sort_keys=True),
                    parsed_fields_json=json.dumps(fields, sort_keys=True),
                )


def _loads_body(body: Any) -> Any:
    if isinstance(body, (dict, list)):
        return body
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None
    return None


def _extract_endpoints(payload: Any) -> Iterator[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        endpoints = data.get("endpoints")
    elif isinstance(data, list):
        endpoints = data
    else:
        endpoints = None
    if not isinstance(endpoints, list):
        return
    for endpoint in endpoints:
        if isinstance(endpoint, dict):
            yield endpoint


def _parsed_fields(
    *,
    router_model_id: str,
    url: Any,
    http_status: int | None,
    endpoint: dict[str, Any],
) -> dict[str, Any]:
    pricing = endpoint.get("pricing") if isinstance(endpoint.get("pricing"), dict) else {}
    provider_id, region = _provider_parts(endpoint)
    fields: dict[str, Any] = {
        "router_model_id": router_model_id,
        "provider_id": provider_id,
        "provider_name": endpoint.get("provider_name"),
        "endpoint_model_id": endpoint.get("model_id") or endpoint.get("id") or router_model_id,
        "url": url,
        "http_status": http_status,
    }
    for key in (
        "context_length",
        "max_completion_tokens",
        "max_prompt_tokens",
        "status",
    ):
        coerced = _coerce_int(endpoint.get(key))
        if coerced is not None:
            fields[key] = coerced
    for key in ("throughput_last_30m", "latency_last_30m"):
        coerced = _coerce_float(endpoint.get(key))
        if coerced is not None:
            fields[key] = coerced
    for raw_key, parsed_key in (
        ("prompt", "price_prompt"),
        ("completion", "price_completion"),
        ("request", "price_request"),
        ("image", "price_image"),
    ):
        coerced = _coerce_float(pricing.get(raw_key))
        if coerced is not None:
            fields[parsed_key] = coerced
    for key in ("tag", "quantization", "supported_parameters"):
        if key in endpoint:
            fields[key] = endpoint[key]
    if region:
        fields["region"] = region
    return {key: value for key, value in fields.items() if value is not None}


def _provider_parts(endpoint: dict[str, Any]) -> tuple[str | None, str | None]:
    tag = endpoint.get("tag")
    if isinstance(tag, str) and tag.strip():
        parts = [part for part in tag.strip().split("/") if part]
        provider_id = _slug(parts[0])
        region = "/".join(parts[1:]) if len(parts) > 1 else None
        return provider_id, region
    return _slug(endpoint.get("provider_id") or endpoint.get("provider_name") or endpoint.get("name")), None


def _slug(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if math.isfinite(amount) else None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
