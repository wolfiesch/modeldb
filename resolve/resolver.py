"""Confidence-ladder entity resolution for parsed source model records."""

from __future__ import annotations

import json
import sqlite3
import sys
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ingest.base import connect, utcnow
from resolve.normalize import (
    extract_date_tokens,
    extract_modifiers,
    extract_surface_prefix,
    normalize_alias,
)

EXACT_PROVIDER_DOC = 1.0
EXPLICIT_BRIDGE = 0.95  # hugging_face_id / models.dev weights URL / HF base_model tag
SNAPSHOT_DATE_MATCH = 0.9
RELEASE_DATE_NAME_PRICE = 0.7
NAME_ONLY = 0.3  # Never auto-merge name-only matches.
AUTO_MERGE_THRESHOLD = SNAPSHOT_DATE_MATCH


class ResolutionMethod(StrEnum):
    EXACT_PROVIDER_DOC = "exact_provider_doc"
    HF_ID_BRIDGE = "hf_id_bridge"
    CANONICAL_SLUG_BRIDGE = "canonical_slug_bridge"
    SOURCE_BASE_MODEL = "source_base_model"
    NORMALIZED_MATCH = "normalized_match"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True)
class Candidate:
    model_id: int | None
    confidence: float
    method: ResolutionMethod
    reason: str
    features: dict[str, Any]


def resolve_record(conn: sqlite3.Connection, source_model_record_id: int) -> int | None:
    """Resolve one source_model_record to a model_alias or queue it for review.

    The M0 implementation wires the durable control flow and DB writes. M1 fills
    in richer candidate scoring for release dates, pricing, and source-specific
    provider docs.
    """

    record = _load_source_record(conn, source_model_record_id)
    alias_string = record["source_model_id"]
    alias_normalized = normalize_alias(alias_string)
    parsed_fields = _loads_json(record["parsed_fields_json"])
    raw_record = _loads_json(record["raw_record_json"])
    features = _resolution_features(alias_string, record, parsed_fields, raw_record)

    candidate = _best_candidate(conn, alias_string, alias_normalized, parsed_fields, raw_record, features)
    if candidate.model_id is not None and candidate.confidence >= AUTO_MERGE_THRESHOLD:
        alias_id = upsert_alias(
            conn,
            source_id=record["source_id"],
            alias_string=alias_string,
            alias_normalized=alias_normalized,
            alias_kind=_alias_kind(record["source_id"], alias_string, parsed_fields, raw_record),
            model_id=candidate.model_id,
            resolution_method=candidate.method.value,
            confidence=candidate.confidence,
            source_snapshot_id=record["source_snapshot_id"],
        )
        conn.execute(
            "UPDATE source_model_record SET model_alias_id = ? WHERE id = ?",
            (alias_id, source_model_record_id),
        )
        return alias_id

    enqueue_ambiguous(
        conn,
        source_record_id=source_model_record_id,
        candidate_model_id=candidate.model_id,
        reason=candidate.reason,
        features={**features, **candidate.features, "confidence": candidate.confidence},
    )
    return None

def drain_accepted_queue(conn: sqlite3.Connection, *, limit: int | None = None) -> dict[str, int]:
    """Materialize accepted review-queue rows into durable model aliases."""

    params: list[Any] = []
    limit_clause = ""
    if limit is not None:
        limit_clause = " LIMIT ?"
        params.append(limit)

    rows = conn.execute(
        f"""
        SELECT id, source_record_id, candidate_model_id, features_json
        FROM entity_resolution_queue
        WHERE status = 'accepted'
          AND resolved_at IS NULL
          AND candidate_model_id IS NOT NULL
        ORDER BY id
        {limit_clause}
        """,
        params,
    ).fetchall()

    processed = 0
    aliases_upserted = 0
    records_updated = 0
    skipped = 0
    for queue_id, source_record_id, candidate_model_id, features_json in rows:
        features = _loads_json(features_json)
        candidates = features.get("provider_scoped_candidates")
        if not isinstance(candidates, list):
            candidates = []

        alias_ids: list[int] = []
        record = _load_source_record(conn, int(source_record_id))
        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            alias_string = candidate.strip()
            alias_id = upsert_alias(
                conn,
                source_id=record["source_id"],
                alias_string=alias_string,
                alias_normalized=normalize_alias(alias_string),
                alias_kind="api_model_id",
                model_id=int(candidate_model_id),
                resolution_method="manual_review",
                confidence=1.0,
                source_snapshot_id=record["source_snapshot_id"],
            )
            alias_ids.append(alias_id)
            aliases_upserted += 1

        if not alias_ids:
            skipped += 1
            continue

        conn.execute(
            "UPDATE source_model_record SET model_alias_id = ? WHERE id = ?",
            (alias_ids[0], int(source_record_id)),
        )
        records_updated += 1
        conn.execute(
            """
            UPDATE entity_resolution_queue
            SET resolved_at = ?
            WHERE id = ?
            """,
            (utcnow(), int(queue_id)),
        )
        processed += 1

    return {
        "processed": processed,
        "aliases_upserted": aliases_upserted,
        "records_updated": records_updated,
        "skipped": skipped,
    }



def upsert_alias(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    alias_string: str,
    alias_normalized: str,
    alias_kind: str,
    model_id: int | None,
    resolution_method: str,
    confidence: float,
    source_snapshot_id: int | None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    provider_surface_id: int | None = None,
    artifact_id: int | None = None,
) -> int:
    """Insert or update one durable alias row and return its id."""

    now = utcnow()
    existing = conn.execute(
        """
        SELECT id FROM model_alias
        WHERE source_id = ?
          AND alias_string = ?
          AND alias_kind = ?
          AND COALESCE(valid_from, '') = COALESCE(?, '')
        """,
        (source_id, alias_string, alias_kind, valid_from),
    ).fetchone()
    if existing:
        alias_id = int(existing[0])
        conn.execute(
            """
            UPDATE model_alias
            SET alias_normalized = ?,
                model_id = ?,
                provider_surface_id = ?,
                artifact_id = ?,
                valid_to = ?,
                resolution_method = ?,
                confidence = ?,
                source_snapshot_id = ?,
                last_seen_at = ?
            WHERE id = ?
            """,
            (
                alias_normalized,
                model_id,
                provider_surface_id,
                artifact_id,
                valid_to,
                resolution_method,
                confidence,
                source_snapshot_id,
                now,
                alias_id,
            ),
        )
        return alias_id

    cursor = conn.execute(
        """
        INSERT INTO model_alias (
          source_id, alias_string, alias_normalized, alias_kind, model_id,
          provider_surface_id, artifact_id, valid_from, valid_to,
          resolution_method, confidence, source_snapshot_id,
          first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            alias_string,
            alias_normalized,
            alias_kind,
            model_id,
            provider_surface_id,
            artifact_id,
            valid_from,
            valid_to,
            resolution_method,
            confidence,
            source_snapshot_id,
            now,
            now,
        ),
    )
    return int(cursor.lastrowid)


def enqueue_ambiguous(
    conn: sqlite3.Connection,
    *,
    source_record_id: int,
    candidate_model_id: int | None,
    reason: str,
    features: dict[str, Any],
) -> int:
    """Insert a pending entity-resolution review item and return its id."""

    features_json = json.dumps(features, sort_keys=True)
    existing = conn.execute(
        """
        SELECT id FROM entity_resolution_queue
        WHERE source_record_id = ?
          AND COALESCE(candidate_model_id, -1) = COALESCE(?, -1)
          AND status = 'pending'
        """,
        (source_record_id, candidate_model_id),
    ).fetchone()
    if existing:
        queue_id = int(existing[0])
        conn.execute(
            """
            UPDATE entity_resolution_queue
            SET reason = ?, features_json = ?
            WHERE id = ?
            """,
            (reason, features_json, queue_id),
        )
        return queue_id

    cursor = conn.execute(
        """
        INSERT INTO entity_resolution_queue (
          source_record_id, candidate_model_id, reason, features_json, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (source_record_id, candidate_model_id, reason, features_json, utcnow()),
    )
    return int(cursor.lastrowid)


def _load_source_record(conn: sqlite3.Connection, source_model_record_id: int) -> sqlite3.Row:
    old_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT smr.id,
                   smr.source_snapshot_id,
                   smr.source_model_id,
                   smr.display_name,
                   smr.provider_name,
                   smr.raw_record_json,
                   smr.parsed_fields_json,
                   ss.source_id
            FROM source_model_record AS smr
            JOIN source_snapshot AS ss ON ss.id = smr.source_snapshot_id
            WHERE smr.id = ?
            """,
            (source_model_record_id,),
        ).fetchone()
    finally:
        conn.row_factory = old_factory
    if row is None:
        raise ValueError(f"source_model_record not found: {source_model_record_id}")
    return row


def _best_candidate(
    conn: sqlite3.Connection,
    alias_string: str,
    alias_normalized: str,
    parsed_fields: dict[str, Any],
    raw_record: dict[str, Any],
    features: dict[str, Any],
) -> Candidate:
    exact = _match_existing_alias(conn, alias_string)
    if exact is not None:
        return Candidate(
            model_id=exact,
            confidence=EXACT_PROVIDER_DOC,
            method=ResolutionMethod.EXACT_PROVIDER_DOC,
            reason="exact provider alias already resolves to a canonical model",
            features={},
        )

    bridge_model_id, bridge_key = _match_hf_bridge(conn, parsed_fields, raw_record)
    if bridge_model_id is not None:
        return Candidate(
            model_id=bridge_model_id,
            confidence=EXPLICIT_BRIDGE,
            method=ResolutionMethod.HF_ID_BRIDGE,
            reason=f"explicit Hugging Face bridge matched {bridge_key}",
            features={"bridge_key": bridge_key},
        )

    normalized = _match_normalized_alias(conn, alias_normalized)
    if normalized is not None and features["date_tokens"]:
        return Candidate(
            model_id=normalized,
            confidence=SNAPSHOT_DATE_MATCH,
            method=ResolutionMethod.NORMALIZED_MATCH,
            reason="normalized alias matched and name carries a snapshot date",
            features={},
        )

    # TODO(M1): score release_date + name + price agreement using parsed model
    # fields from models.dev, OpenRouter, and llm-prices before falling back to
    # name-only review.
    if normalized is not None:
        return Candidate(
            model_id=normalized,
            confidence=NAME_ONLY,
            method=ResolutionMethod.NORMALIZED_MATCH,
            reason="normalized name-only match requires manual review",
            features={},
        )

    return Candidate(
        model_id=None,
        confidence=0.0,
        method=ResolutionMethod.MANUAL_REVIEW,
        reason="no high-confidence candidate found",
        features={},
    )


def _match_existing_alias(conn: sqlite3.Connection, alias_string: str) -> int | None:
    row = conn.execute(
        """
        SELECT model_id FROM model_alias
        WHERE alias_string = ? AND model_id IS NOT NULL
        ORDER BY confidence DESC, last_seen_at DESC
        LIMIT 1
        """,
        (alias_string,),
    ).fetchone()
    return int(row[0]) if row else None


def _match_hf_bridge(
    conn: sqlite3.Connection,
    parsed_fields: dict[str, Any],
    raw_record: dict[str, Any],
) -> tuple[int | None, str | None]:
    bridge = _first_string(
        parsed_fields,
        raw_record,
        keys=("hugging_face_id", "hf_repo_id", "hf_repo", "base_model"),
    )
    if not bridge:
        return None, None

    artifact = conn.execute(
        """
        SELECT model_id FROM model_artifact
        WHERE artifact_ref = ? AND model_id IS NOT NULL
        LIMIT 1
        """,
        (bridge,),
    ).fetchone()
    if artifact:
        return int(artifact[0]), bridge

    alias = conn.execute(
        """
        SELECT model_id FROM model_alias
        WHERE alias_string = ?
          AND alias_kind = 'hf_repo_id'
          AND model_id IS NOT NULL
        ORDER BY confidence DESC, last_seen_at DESC
        LIMIT 1
        """,
        (bridge,),
    ).fetchone()
    if alias:
        return int(alias[0]), bridge
    return None, bridge


def _match_normalized_alias(conn: sqlite3.Connection, alias_normalized: str) -> int | None:
    row = conn.execute(
        """
        SELECT model_id FROM model_alias
        WHERE alias_normalized = ? AND model_id IS NOT NULL
        ORDER BY confidence DESC, last_seen_at DESC
        LIMIT 1
        """,
        (alias_normalized,),
    ).fetchone()
    return int(row[0]) if row else None


def _resolution_features(
    alias_string: str,
    record: sqlite3.Row,
    parsed_fields: dict[str, Any],
    raw_record: dict[str, Any],
) -> dict[str, Any]:
    bridge = _first_string(
        parsed_fields,
        raw_record,
        keys=("hugging_face_id", "hf_repo_id", "hf_repo", "base_model"),
    )
    return {
        "source_id": record["source_id"],
        "source_model_id": alias_string,
        "display_name": record["display_name"],
        "provider_name": record["provider_name"],
        "alias_normalized": normalize_alias(alias_string),
        "date_tokens": extract_date_tokens(alias_string),
        "surface_prefix": extract_surface_prefix(alias_string),
        "modifiers": extract_modifiers(alias_string),
        "hf_bridge": bridge,
    }


def _alias_kind(
    source_id: str,
    alias_string: str,
    parsed_fields: dict[str, Any],
    raw_record: dict[str, Any],
) -> str:
    bridge = _first_string(parsed_fields, raw_record, keys=("hugging_face_id", "hf_repo_id", "hf_repo"))
    if bridge and alias_string == bridge:
        return "hf_repo_id"
    if source_id == "openrouter":
        return "router_id"
    if source_id in {"models_dev", "llm_prices", "litellm"}:
        return "api_model_id"
    if extract_surface_prefix(alias_string) == "bedrock":
        return "bedrock_id"
    return "api_model_id"


def _loads_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _first_string(*objects: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for obj in objects:
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["drain-accepted"]:
        with connect() as conn:
            summary = drain_accepted_queue(conn)
            conn.commit()
        print(json.dumps(summary, sort_keys=True))
        return 0
    if len(argv) != 1:
        print("Usage: python -m resolve.resolver SOURCE_MODEL_RECORD_ID")
        print("       python -m resolve.resolver drain-accepted")
        return 2
    with connect() as conn:
        alias_id = resolve_record(conn, int(argv[0]))
        conn.commit()
    print(f"resolved alias_id={alias_id}" if alias_id is not None else "queued for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
