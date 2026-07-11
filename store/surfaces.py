from __future__ import annotations

import json
import sqlite3
from typing import Any

from resolve.normalize import canonical_org
from store.spine import link_model


_SOURCE_RECORD_SQL = """
    SELECT smr.source_snapshot_id, smr.source_model_id, smr.raw_record_json,
           smr.parsed_fields_json
    FROM source_model_record smr
    JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
    WHERE ss.source_id = 'models_dev'
"""

_SURFACE_TYPES = {
    "togetherai": "together",
    "amazon-bedrock": "bedrock",
    "google-vertex": "vertex",
    "groq": "groq",
    "azure": "azure",
    "openrouter": "openrouter",
}

_METADATA_FIELDS = (
    "context_window",
    "max_output",
    "open_weights",
    "tool_call",
    "reasoning",
    "attachment",
    "modalities",
)


def _json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_suffix(source_model_id: str) -> str:
    return source_model_id.split("/", 1)[1] if "/" in source_model_id else source_model_id


def surface_identity(
    *,
    source_model_id: str,
    parsed_fields: dict[str, Any],
    canonical_developer_id: str | None,
) -> tuple[str, str | None, str | None, str]:
    """Return provider_id, surface_type, region, endpoint_model_id for a source row."""
    provider_id = parsed_fields.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id:
        provider_id = source_model_id.split("/", 1)[0] if "/" in source_model_id else None
    if not provider_id:
        provider_id = "unknown"

    endpoint_model_id = parsed_fields.get("model_id")
    if not isinstance(endpoint_model_id, str) or not endpoint_model_id:
        endpoint_model_id = _source_suffix(source_model_id)

    region = parsed_fields.get("region")
    if not isinstance(region, str) or not region:
        region = None

    provider_org = canonical_org(provider_id)
    if canonical_developer_id and provider_org == canonical_developer_id:
        surface_type = "first_party"
    else:
        surface_type = _SURFACE_TYPES.get(provider_id, "third_party")

    return provider_id, surface_type, region, endpoint_model_id


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _nested(mapping: dict[str, Any], *path: str) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _metadata(parsed_fields: dict[str, Any], raw_record: dict[str, Any]) -> str | None:
    modalities = _first_present(
        parsed_fields.get("modalities"),
        raw_record.get("modalities"),
    )
    if modalities is None:
        inputs = parsed_fields.get("input_modalities")
        outputs = parsed_fields.get("output_modalities")
        if inputs is not None or outputs is not None:
            modalities = {"input": inputs, "output": outputs}

    metadata = {
        "context_window": _first_present(
            parsed_fields.get("context_window"),
            parsed_fields.get("context_limit"),
            parsed_fields.get("context_length"),
            parsed_fields.get("top_provider_context_length"),
            _nested(raw_record, "limit", "context"),
            raw_record.get("context_length"),
        ),
        "max_output": _first_present(
            parsed_fields.get("max_output"),
            parsed_fields.get("output_limit"),
            parsed_fields.get("top_provider_max_completion_tokens"),
            _nested(raw_record, "limit", "output"),
            _nested(raw_record, "top_provider", "max_completion_tokens"),
        ),
        "open_weights": _first_present(parsed_fields.get("open_weights"), raw_record.get("open_weights")),
        "tool_call": _first_present(
            parsed_fields.get("tool_call"),
            parsed_fields.get("tool_calls"),
            raw_record.get("tool_call"),
            raw_record.get("tool_calls"),
        ),
        "reasoning": _first_present(parsed_fields.get("reasoning"), raw_record.get("reasoning")),
        "attachment": _first_present(parsed_fields.get("attachment"), raw_record.get("attachment")),
        "modalities": modalities,
    }
    useful = {key: metadata[key] for key in _METADATA_FIELDS if metadata.get(key) is not None}
    return json.dumps(useful, sort_keys=True) if useful else None


def _canonical_developer(conn: sqlite3.Connection, model_id: int) -> str | None:
    row = conn.execute("SELECT developer_id FROM model WHERE id = ?", (model_id,)).fetchone()
    developer_id = row[0] if row else None
    return developer_id if isinstance(developer_id, str) and developer_id else None


def _delete_models_dev_surfaces(conn: sqlite3.Connection) -> None:
    models_dev_surface_ids = """
        SELECT ps.id
        FROM provider_surface ps
        JOIN source_snapshot ss ON ss.id = ps.source_snapshot_id
        WHERE ss.source_id = 'models_dev'
    """
    conn.execute(
        f"UPDATE price_component SET provider_surface_id = NULL WHERE provider_surface_id IN ({models_dev_surface_ids})"
    )
    conn.execute(
        """
        DELETE FROM provider_surface
        WHERE source_snapshot_id IN (SELECT id FROM source_snapshot WHERE source_id = 'models_dev')
        """
    )


def _upsert_surface(
    conn: sqlite3.Connection,
    *,
    provider_id: str,
    surface_type: str | None,
    region: str | None,
    endpoint_model_id: str,
    model_id: int,
    source_snapshot_id: int,
    metadata_json: str | None,
) -> bool:
    existing = conn.execute(
        """
        SELECT id FROM provider_surface
        WHERE provider_id = ?
          AND surface_type IS ?
          AND region IS ?
          AND endpoint_model_id = ?
        """,
        (provider_id, surface_type, region, endpoint_model_id),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE provider_surface
            SET model_id = ?, source_snapshot_id = ?, metadata_json = ?
            WHERE id = ?
            """,
            (model_id, source_snapshot_id, metadata_json, existing[0]),
        )
        return False

    conn.execute(
        """
        INSERT INTO provider_surface
          (provider_id, surface_type, region, endpoint_model_id, model_id,
           source_snapshot_id, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (provider_id, surface_type, region, endpoint_model_id, model_id, source_snapshot_id, metadata_json),
    )
    return True


def promote_surfaces(conn: sqlite3.Connection) -> dict[str, int]:
    _delete_models_dev_surfaces(conn)

    inserted = 0
    refreshed = 0
    unmatched = 0
    seen: set[tuple[str, str | None, str | None, str]] = set()

    for source_snapshot_id, source_model_id, raw_record_json, parsed_fields_json in conn.execute(
        _SOURCE_RECORD_SQL
    ):
        parsed_fields = _json_object(parsed_fields_json)
        model_id = link_model(
            conn,
            source_id="models_dev",
            source_model_id=source_model_id,
            parsed_fields=parsed_fields,
        )
        if model_id is None:
            unmatched += 1
            continue

        provider_id, surface_type, region, endpoint_model_id = surface_identity(
            source_model_id=source_model_id,
            parsed_fields=parsed_fields,
            canonical_developer_id=_canonical_developer(conn, model_id),
        )
        key = (provider_id, surface_type, region, endpoint_model_id)
        if key in seen:
            refreshed += 1
            continue
        seen.add(key)

        if _upsert_surface(
            conn,
            provider_id=provider_id,
            surface_type=surface_type,
            region=region,
            endpoint_model_id=endpoint_model_id,
            model_id=model_id,
            source_snapshot_id=source_snapshot_id,
            metadata_json=_metadata(parsed_fields, _json_object(raw_record_json)),
        ):
            inserted += 1
        else:
            refreshed += 1

    return {"inserted": inserted, "refreshed": refreshed, "unmatched": unmatched}


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_surfaces(c))
        c.commit()
