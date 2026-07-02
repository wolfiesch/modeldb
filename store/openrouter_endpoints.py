from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Callable, Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ingest.base import utcnow
from store.spine import link_model

SOURCE_ID = "openrouter_endpoints"
OPENROUTER_SOURCE_ID = "openrouter"
USER_AGENT = "modeldb-ingest/0.1"
DEFAULT_LIMIT = 150
BASE_URL = "https://openrouter.ai/api/v1/models"

Fetcher = Callable[[str], tuple[int, bytes]]

_PRICE_COMPONENTS = (
    ("prompt", "input_token", "token", True),
    ("completion", "output_token", "token", True),
    ("request", "request", "request", False),
    ("image", "image", "image", False),
)

_SOURCE_MARKER_COMPACT = '%"source_id":"openrouter_endpoints"%'
_SOURCE_MARKER_SPACED = '%"source_id": "openrouter_endpoints"%'


def _fetch_url(url: str) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=30) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        return int(exc.code), exc.read()
    except URLError as exc:
        error = {"error": str(exc.reason)}
        return 0, json.dumps(error, sort_keys=True).encode("utf-8")


def _json_loads(value: str | bytes | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


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


def _slug(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or None


def _endpoint_url(router_model_id: str, raw_record_json: str | None) -> str:
    raw = _json_loads(raw_record_json)
    details_url = _find_details_url(raw, router_model_id)
    if details_url:
        return _as_endpoint_url(details_url, router_model_id)
    return f"{BASE_URL}/{quote(router_model_id, safe='/')}/endpoints"


def _find_details_url(value: Any, router_model_id: str) -> str | None:
    if isinstance(value, dict):
        for key in ("endpoints_url", "endpoint_url", "details_url", "url", "href", "link"):
            candidate = value.get(key)
            if isinstance(candidate, str) and router_model_id in candidate:
                return candidate
        for nested in value.values():
            found = _find_details_url(nested, router_model_id)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_details_url(nested, router_model_id)
            if found:
                return found
    elif isinstance(value, str) and router_model_id in value and "/models/" in value:
        return value
    return None


def _as_endpoint_url(url: str, router_model_id: str) -> str:
    if url.startswith("/"):
        url = "https://openrouter.ai" + url
    if url.endswith("/endpoints"):
        return url
    marker = f"/models/{router_model_id}"
    if marker in url:
        return url.split("?", 1)[0].rstrip("/") + "/endpoints"
    return f"{BASE_URL}/{quote(router_model_id, safe='/')}/endpoints"


def _known_openrouter_records(conn: sqlite3.Connection, limit: int) -> list[tuple[str, int, str | None]]:
    return [
        (str(row[0]), int(row[1]), row[2])
        for row in conn.execute(
            """
            SELECT smr.source_model_id, MAX(smr.source_snapshot_id) AS source_snapshot_id,
                   (
                     SELECT newer.raw_record_json
                     FROM source_model_record newer
                     JOIN source_snapshot newer_ss ON newer_ss.id = newer.source_snapshot_id
                     WHERE newer.source_model_id = smr.source_model_id
                       AND newer_ss.source_id = ?
                     ORDER BY newer.source_snapshot_id DESC, newer.id DESC
                     LIMIT 1
                   ) AS raw_record_json
            FROM source_model_record smr
            JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
            WHERE ss.source_id = ?
            GROUP BY smr.source_model_id
            ORDER BY source_snapshot_id DESC, smr.source_model_id
            LIMIT ?
            """,
            (OPENROUTER_SOURCE_ID, OPENROUTER_SOURCE_ID, max(0, int(limit))),
        )
    ]


def _extract_endpoints(payload: Any) -> Iterable[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        endpoints = data.get("endpoints")
    elif isinstance(data, list):
        endpoints = data
    else:
        endpoints = None
    if not isinstance(endpoints, list):
        return ()
    return (endpoint for endpoint in endpoints if isinstance(endpoint, dict))


def _provider_parts(endpoint: dict[str, Any]) -> tuple[str | None, str | None]:
    tag = endpoint.get("tag")
    if isinstance(tag, str) and tag.strip():
        parts = [part for part in tag.strip().split("/") if part]
        provider_id = _slug(parts[0])
        region = "/".join(parts[1:]) if len(parts) > 1 else None
        return provider_id, region
    return _slug(endpoint.get("provider_id") or endpoint.get("provider_name") or endpoint.get("name")), None


def _route_metadata(
    *,
    router_model_id: str,
    url: str,
    http_status: int,
    endpoint: dict[str, Any],
) -> dict[str, Any]:
    keys = (
        "name",
        "provider_name",
        "tag",
        "context_length",
        "max_completion_tokens",
        "max_prompt_tokens",
        "quantization",
        "status",
        "uptime_last_30m",
        "uptime_last_5m",
        "uptime_last_1d",
        "supports_implicit_caching",
        "latency_last_30m",
        "throughput_last_30m",
        "supported_parameters",
    )
    metadata: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "router_model_id": router_model_id,
        "url": url,
        "http_status": http_status,
    }
    for key in keys:
        if key in endpoint:
            metadata[key] = endpoint[key]
    return metadata


def _insert_price(
    conn: sqlite3.Connection,
    *,
    model_id: int,
    provider_surface_id: int,
    component: str,
    unit: str,
    amount: float,
    normalized: float | None,
    source_snapshot_id: int,
    valid_from: str,
) -> None:
    conn.execute(
        """
        INSERT INTO price_component
          (model_id, provider_surface_id, source_id, component, unit, currency, amount,
           normalized_usd_per_1m_tokens, tier_condition_json, valid_from, valid_to,
           source_snapshot_id)
        VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, NULL, ?, NULL, ?)
        """,
        (
            model_id,
            provider_surface_id,
            SOURCE_ID,
            component,
            unit,
            amount,
            normalized,
            valid_from,
            source_snapshot_id,
        ),
    )


def _insert_surface(
    conn: sqlite3.Connection,
    *,
    provider_id: str,
    region: str | None,
    endpoint_model_id: str,
    model_id: int,
    source_snapshot_id: int,
    metadata: dict[str, Any],
) -> int:
    metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))
    row = conn.execute(
        """
        SELECT id FROM provider_surface
        WHERE provider_id = ? AND surface_type = 'openrouter'
          AND region IS ? AND endpoint_model_id = ?
        """,
        (provider_id, region, endpoint_model_id),
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE provider_surface
            SET model_id = ?, source_snapshot_id = ?, metadata_json = ?
            WHERE id = ?
            """,
            (model_id, source_snapshot_id, metadata_json, row[0]),
        )
        return int(row[0])

    cursor = conn.execute(
        """
        INSERT INTO provider_surface
          (provider_id, surface_type, region, endpoint_model_id, model_id,
           source_snapshot_id, metadata_json)
        VALUES (?, 'openrouter', ?, ?, ?, ?, ?)
        """,
        (provider_id, region, endpoint_model_id, model_id, source_snapshot_id, metadata_json),
    )
    return int(cursor.lastrowid)


def _ensure_source(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO source
          (id, name, base_url, ingestion_class, auth_type, update_cadence, notes)
        VALUES (?, 'OpenRouter endpoint routes', ?, 'A', 'none', 'on demand',
                'Per-provider OpenRouter /endpoints route surfaces and prices.')
        """,
        (SOURCE_ID, BASE_URL),
    )


def _delete_owned_rows(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM price_component WHERE source_id = ?", (SOURCE_ID,))
    conn.execute(
        """
        DELETE FROM provider_surface
        WHERE surface_type = 'openrouter'
          AND (metadata_json LIKE ? OR metadata_json LIKE ?)
        """,
        (_SOURCE_MARKER_COMPACT, _SOURCE_MARKER_SPACED),
    )


def promote_openrouter_endpoints(
    conn: sqlite3.Connection,
    *,
    limit: int = DEFAULT_LIMIT,
    fetcher: Fetcher | None = None,
) -> dict[str, int]:
    """Fetch capped OpenRouter endpoint routes and promote surfaces and prices.

    The crawl root is the existing SQLite OpenRouter catalog records. This avoids an
    unbounded network crawl and keeps endpoint facts attached to canonical models via
    the already-bridged OpenRouter aliases.
    """
    fetch = fetcher or _fetch_url
    capped_limit = max(0, min(int(limit), DEFAULT_LIMIT))
    records = _known_openrouter_records(conn, capped_limit)
    _ensure_source(conn)
    _delete_owned_rows(conn)

    summary = {
        "models_considered": len(records),
        "urls_fetched": 0,
        "fetch_errors": 0,
        "routes_seen": 0,
        "surfaces_inserted": 0,
        "prices_inserted": 0,
        "unmatched": 0,
        "skipped_routes": 0,
    }
    valid_from = utcnow()

    for router_model_id, source_snapshot_id, raw_record_json in records:
        model_id = link_model(
            conn,
            source_id=OPENROUTER_SOURCE_ID,
            source_model_id=router_model_id,
            parsed_fields={},
        )
        if model_id is None:
            summary["unmatched"] += 1
            continue

        url = _endpoint_url(router_model_id, raw_record_json)
        status, body = fetch(url)
        summary["urls_fetched"] += 1
        if status != 200:
            summary["fetch_errors"] += 1
            continue

        payload = _json_loads(body)
        for endpoint in _extract_endpoints(payload):
            summary["routes_seen"] += 1
            provider_id, region = _provider_parts(endpoint)
            endpoint_model_id = endpoint.get("model_id") or endpoint.get("id") or router_model_id
            if provider_id is None or not endpoint_model_id:
                summary["skipped_routes"] += 1
                continue

            metadata = _route_metadata(
                router_model_id=router_model_id,
                url=url,
                http_status=status,
                endpoint=endpoint,
            )
            surface_id = _insert_surface(
                conn,
                provider_id=provider_id,
                region=region,
                endpoint_model_id=str(endpoint_model_id),
                model_id=model_id,
                source_snapshot_id=source_snapshot_id,
                metadata=metadata,
            )
            summary["surfaces_inserted"] += 1

            pricing = endpoint.get("pricing") if isinstance(endpoint.get("pricing"), dict) else {}
            for price_key, component, unit, token_normalized in _PRICE_COMPONENTS:
                amount = _coerce_float(pricing.get(price_key))
                if amount is None:
                    continue
                _insert_price(
                    conn,
                    model_id=model_id,
                    provider_surface_id=surface_id,
                    component=component,
                    unit=unit,
                    amount=amount,
                    normalized=amount * 1_000_000 if token_normalized else None,
                    source_snapshot_id=source_snapshot_id,
                    valid_from=valid_from,
                )
                summary["prices_inserted"] += 1

    return summary


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_openrouter_endpoints(c))
        c.commit()
