import json
from typing import Any

from ingest.base import utcnow
from store.spine import link_model


_SOURCE_RECORD_SQL = """
    SELECT ss.source_id, smr.source_snapshot_id, smr.source_model_id, smr.parsed_fields_json
    FROM source_model_record smr
    JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
    WHERE ss.id IN (
        SELECT MAX(id) FROM source_snapshot
        WHERE source_id IN ('models_dev','openrouter')
        GROUP BY source_id
    )
"""

# Mirrors store/spine.py: promote only the newest snapshot per source; reading
# every historical snapshot minted one capability row per snapshot per refresh.

_CAPABILITY_COLUMNS = "model_id, capability, value, source_snapshot_id, confidence"

_SOURCE_CONFIDENCE = {
    "models_dev": 1.0,
    "openrouter": 0.9,
}

_SOURCE_FIELDS = {
    "models_dev": {
        "context_window": "context_limit",
        "max_output": "output_limit",
        "input_modalities": "input_modalities",
        "output_modalities": "output_modalities",
    },
    "openrouter": {
        "context_window": "context_length",
        "max_output": "top_provider_max_completion_tokens",
        "input_modalities": "input_modalities",
        "output_modalities": "output_modalities",
    },
}

_MODALITY_CAPABILITIES = {"input_modalities", "output_modalities"}


def _parsed_fields(parsed_fields_json: str | None) -> dict[str, Any]:
    if not parsed_fields_json:
        return {}
    try:
        parsed = json.loads(parsed_fields_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _capability_value(capability: str, raw_value: Any) -> str | None:
    if raw_value is None:
        return None

    try:
        if capability in _MODALITY_CAPABILITIES:
            if not isinstance(raw_value, list):
                return None
            return json.dumps(sorted(raw_value))
        return str(int(raw_value))
    except (TypeError, ValueError):
        return None


def _source_capabilities(source_id: str, parsed_fields: dict[str, Any]) -> list[tuple[str, str]]:
    capabilities: list[tuple[str, str]] = []
    for capability, field in _SOURCE_FIELDS[source_id].items():
        value = _capability_value(capability, parsed_fields.get(field))
        if value is None:
            continue
        capabilities.append((capability, value))
    return capabilities


def _insert_capability(
    conn,
    *,
    model_id: int,
    capability: str,
    value: str,
    source_snapshot_id: int,
    confidence: float,
) -> None:
    conn.execute(
        f"""
        INSERT OR REPLACE INTO model_capability ({_CAPABILITY_COLUMNS})
        VALUES (?, ?, ?, ?, ?)
        """,
        (model_id, capability, value, source_snapshot_id, confidence),
    )


def promote_capabilities(conn) -> dict[str, int]:
    conn.execute(
        """
        DELETE FROM model_capability
        WHERE source_snapshot_id IN (
            SELECT id FROM source_snapshot WHERE source_id IN ('models_dev','openrouter')
        )
        """
    )

    inserted = 0
    unmatched = 0
    models_with_caps: set[int] = set()

    for source_id, source_snapshot_id, source_model_id, parsed_fields_json in conn.execute(
        _SOURCE_RECORD_SQL
    ):
        parsed_fields = _parsed_fields(parsed_fields_json)
        try:
            capabilities = _source_capabilities(source_id, parsed_fields)
        except Exception:
            continue
        if not capabilities:
            continue

        try:
            model_id = link_model(
                conn,
                source_id=source_id,
                source_model_id=source_model_id,
                parsed_fields=parsed_fields,
            )
        except Exception:
            unmatched += 1
            continue
        if model_id is None:
            unmatched += 1
            continue

        confidence = _SOURCE_CONFIDENCE[source_id]
        inserted_for_model = False
        for capability, value in capabilities:
            try:
                _insert_capability(
                    conn,
                    model_id=model_id,
                    capability=capability,
                    value=value,
                    source_snapshot_id=source_snapshot_id,
                    confidence=confidence,
                )
            except Exception:
                continue
            inserted += 1
            inserted_for_model = True
        if inserted_for_model:
            models_with_caps.add(model_id)

    return {
        "inserted": inserted,
        "unmatched": unmatched,
        "models_with_caps": len(models_with_caps),
    }


if __name__ == "__main__":
    from ingest.base import connect

    with connect() as c:
        print(promote_capabilities(c))
        c.commit()
