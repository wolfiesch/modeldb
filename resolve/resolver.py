"""Confidence-ladder entity resolution for parsed source model records."""

from __future__ import annotations

import csv
import io
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

def drain_accepted_queue(conn: sqlite3.Connection, *, limit: int | None = None, dry_run: bool = False) -> dict[str, int | bool]:
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

        valid_aliases = [candidate.strip() for candidate in candidates if isinstance(candidate, str) and candidate.strip()]
        if not valid_aliases:
            skipped += 1
            continue
        record = _load_source_record(conn, int(source_record_id))
        if dry_run:
            aliases_upserted += len(valid_aliases)
            records_updated += 1
            processed += 1
            continue

        alias_ids: list[int] = []
        for alias_string in valid_aliases:
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
        _insert_queue_audit(
            conn,
            queue_id=int(queue_id),
            source_record_id=int(source_record_id),
            candidate_model_id=int(candidate_model_id),
            action="drain",
            details={
                "alias_ids": alias_ids,
                "alias_count": len(alias_ids),
                "model_alias_id": alias_ids[0],
            },
        )
        processed += 1

    return {
        "processed": processed,
        "aliases_upserted": aliases_upserted,
        "records_updated": records_updated,
        "skipped": skipped,
        "dry_run": dry_run,
    }

def accept_queue_row(conn: sqlite3.Connection, *, queue_id: int, candidate_model_id: int) -> dict[str, int]:
    """Mark one pending review row accepted with an explicit target model."""

    model = conn.execute("SELECT id FROM model WHERE id = ?", (candidate_model_id,)).fetchone()
    if model is None:
        raise ValueError(f"candidate model not found: {candidate_model_id}")

    row = conn.execute(
        """
        SELECT id, source_record_id, status, resolved_at, candidate_model_id, features_json
        FROM entity_resolution_queue
        WHERE id = ?
        """,
        (queue_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"queue row not found: {queue_id}")
    if row[2] != "pending" or row[3] is not None or row[4] is not None:
        raise ValueError(f"queue row is not pending without a candidate: {queue_id}")

    cursor = conn.execute(
        """
        UPDATE entity_resolution_queue
        SET candidate_model_id = ?,
            status = 'accepted'
        WHERE id = ?
          AND status = 'pending'
          AND resolved_at IS NULL
          AND candidate_model_id IS NULL
        """,
        (candidate_model_id, queue_id),
    )
    if cursor.rowcount != 1:
        raise ValueError(f"queue row is not pending without a candidate: {queue_id}")
    _insert_queue_audit(
        conn,
        queue_id=queue_id,
        source_record_id=int(row[1]),
        candidate_model_id=candidate_model_id,
        action="accept",
        details={
            "prior_status": row[2],
            "prior_candidate_model_id": row[4],
            "prior_resolved_at": row[3],
        },
    )

    return {"accepted": 1, "queue_id": queue_id, "candidate_model_id": candidate_model_id}

def accept_queue_batch(
    conn: sqlite3.Connection,
    approvals: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Atomically accept an explicit reviewed list of queue/model pairs."""

    conn.execute("SAVEPOINT accept_queue_batch")
    try:
        items = [
            accept_queue_row(
                conn,
                queue_id=_required_int(approval, "queue_id"),
                candidate_model_id=_required_int(approval, "candidate_model_id"),
            )
            for approval in approvals
        ]
        if dry_run:
            conn.execute("ROLLBACK TO accept_queue_batch")
        conn.execute("RELEASE accept_queue_batch")
    except Exception:
        conn.execute("ROLLBACK TO accept_queue_batch")
        conn.execute("RELEASE accept_queue_batch")
        raise
    return {"accepted": len(items), "items": items, "dry_run": dry_run}

def accept_new_model_batch(
    conn: sqlite3.Connection,
    reviews: list[dict[str, Any]],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create explicitly reviewed canonical models and attach reviewed source aliases."""

    conn.execute("SAVEPOINT accept_new_model_batch")
    try:
        items = [_accept_new_model_row(conn, review) for review in reviews]
        if dry_run:
            conn.execute("ROLLBACK TO accept_new_model_batch")
        conn.execute("RELEASE accept_new_model_batch")
    except Exception:
        conn.execute("ROLLBACK TO accept_new_model_batch")
        conn.execute("RELEASE accept_new_model_batch")
        raise
    return {"created": len(items), "items": items, "dry_run": dry_run}


def _accept_new_model_row(conn: sqlite3.Connection, review: dict[str, Any]) -> dict[str, Any]:
    queue_id = _required_int(review, "queue_id")
    canonical_slug = _required_text(review, "canonical_slug")
    developer_id = _required_text(review, "developer_id")
    aliases = _required_text_list(review, "aliases")
    family = _optional_text(review, "family")
    tier_or_variant = _optional_text(review, "tier_or_variant")

    if not canonical_slug.startswith(f"{developer_id}/"):
        raise ValueError("approval.canonical_slug must start with approval.developer_id + '/'")

    existing = conn.execute("SELECT id FROM model WHERE canonical_slug = ?", (canonical_slug,)).fetchone()
    if existing is not None:
        raise ValueError(f"model already exists for canonical_slug: {canonical_slug}; use accept-batch with that model_id")
    organization = conn.execute("SELECT id FROM organization WHERE id = ?", (developer_id,)).fetchone()
    if organization is None:
        raise ValueError(f"organization not found for developer_id: {developer_id}")


    row = conn.execute(
        """
        SELECT erq.source_record_id, erq.status, erq.resolved_at, erq.candidate_model_id,
               smr.model_alias_id, ss.source_id, smr.source_snapshot_id
        FROM entity_resolution_queue erq
        JOIN source_model_record smr ON smr.id = erq.source_record_id
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE erq.id = ?
        """,
        (queue_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"queue row not found: {queue_id}")
    if row[1] != "pending" or row[2] is not None or row[3] is not None:
        raise ValueError(f"queue row is not pending without a candidate: {queue_id}")
    if row[4] is not None:
        raise ValueError(f"source record is already linked: {row[0]}")
    source_id = str(row[5])
    _ensure_review_aliases_available(conn, source_id=source_id, aliases=aliases)


    now = utcnow()
    model_cursor = conn.execute(
        """
        INSERT INTO model (
          canonical_slug, developer_id, family, tier_or_variant,
          canonical_confidence, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'manual_review', ?, ?)
        """,
        (canonical_slug, developer_id, family, tier_or_variant, now, now),
    )
    model_id = int(model_cursor.lastrowid)

    alias_ids = [
        upsert_alias(
            conn,
            source_id=source_id,
            alias_string=alias,
            alias_normalized=normalize_alias(alias),
            alias_kind="api_model_id",
            model_id=model_id,
            resolution_method="manual_review",
            confidence=1.0,
            source_snapshot_id=int(row[6]),
        )
        for alias in aliases
    ]
    conn.execute(
        "UPDATE source_model_record SET model_alias_id = ? WHERE id = ?",
        (alias_ids[0], int(row[0])),
    )
    conn.execute(
        """
        UPDATE entity_resolution_queue
        SET candidate_model_id = ?,
            status = 'resolved',
            resolved_at = ?
        WHERE id = ?
        """,
        (model_id, now, queue_id),
    )
    _insert_queue_audit(
        conn,
        queue_id=queue_id,
        source_record_id=int(row[0]),
        candidate_model_id=model_id,
        action="new_model",
        details={
            "canonical_slug": canonical_slug,
            "developer_id": developer_id,
            "aliases": aliases,
            "model_alias_ids": alias_ids,
        },
    )
    return {
        "queue_id": queue_id,
        "source_record_id": int(row[0]),
        "model_id": model_id,
        "canonical_slug": canonical_slug,
        "developer_id": developer_id,
        "model_alias_ids": alias_ids,
    }

def _ensure_review_aliases_available(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    aliases: list[str],
) -> None:
    seen = set()
    for alias in aliases:
        key = normalize_alias(alias)
        if key in seen:
            raise ValueError(f"duplicate reviewed alias: {alias}")
        seen.add(key)
        existing = conn.execute(
            """
            SELECT id, model_id
            FROM model_alias
            WHERE source_id = ?
              AND alias_string = ?
              AND alias_kind = 'api_model_id'
              AND COALESCE(valid_from, '') = ''
            """,
            (source_id, alias),
        ).fetchone()
        if existing is not None and existing[1] is not None:
            raise ValueError(f"reviewed alias is already linked to model_id {existing[1]}: {alias}")


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"approval.{key} must be an integer")
    return value

def _required_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"approval.{key} must be a non-empty string")
    return value.strip()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"approval.{key} must be a non-empty string when provided")
    return value.strip()


def _required_text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValueError(f"approval.{key} must be a non-empty string array")
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"approval.{key} must be a non-empty string array")
        items.append(item.strip())
    if not items:
        raise ValueError(f"approval.{key} must be a non-empty string array")
    return items



_QUEUE_FAMILY_SUFFIXES = (
    "non-reasoning",
    "reasoning",
    "preview",
    "adaptive",
    "high",
    "medium",
    "low",
    "xhigh",
)


def pending_queue_report(
    conn: sqlite3.Connection,
    *,
    source_id: str = "artificialanalysis",
    sample_limit: int = 3,
) -> dict[str, Any]:
    """Summarize pending null-candidate queue rows for one source."""

    rows = conn.execute(
        """
        SELECT erq.id, erq.source_record_id, erq.features_json,
               smr.source_model_id, smr.display_name
        FROM entity_resolution_queue erq
        JOIN source_model_record smr ON smr.id = erq.source_record_id
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
          AND erq.status = 'pending'
          AND erq.resolved_at IS NULL
          AND erq.candidate_model_id IS NULL
        ORDER BY erq.id
        """,
        (source_id,),
    ).fetchall()

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for queue_id, source_record_id, features_json, source_model_id, display_name in rows:
        features = _loads_json(features_json)
        provider = _text_or_unknown(features.get("model_creator_slug"))
        candidates = _string_list(features.get("provider_scoped_candidates"))
        first_candidate = candidates[0] if candidates else ""
        family = _queue_candidate_family(provider, first_candidate)
        key = (provider, family)
        group = groups.setdefault(
            key,
            {"provider": provider, "family": family, "count": 0, "samples": []},
        )
        group["count"] += 1
        if len(group["samples"]) < sample_limit:
            group["samples"].append(
                {
                    "queue_id": int(queue_id),
                    "source_record_id": int(source_record_id),
                    "source_model_id": source_model_id,
                    "model_name": features.get("model_name") or display_name,
                    "slug": features.get("slug"),
                    "first_candidate": first_candidate or None,
                    "candidate_count": len(candidates),
                }
            )

    ordered_groups = sorted(groups.values(), key=lambda row: (-row["count"], row["provider"], row["family"]))
    return {"source_id": source_id, "total": len(rows), "groups": ordered_groups}

def queue_candidate_options(conn: sqlite3.Connection, queue_id: int, *, limit: int = 10) -> dict[str, Any]:
    """Return read-only candidate model options for one pending review row."""

    row = conn.execute(
        """
        SELECT erq.id, erq.source_record_id, erq.features_json,
               erq.status, erq.candidate_model_id, erq.resolved_at,
               smr.source_model_id, smr.display_name, ss.source_id
        FROM entity_resolution_queue erq
        JOIN source_model_record smr ON smr.id = erq.source_record_id
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE erq.id = ?
          AND erq.status = 'pending'
          AND erq.resolved_at IS NULL
          AND erq.candidate_model_id IS NULL
        """,
        (queue_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"pending null-candidate queue row not found: {queue_id}")
    features = _loads_json(row[2])
    provider = _text_or_unknown(features.get("model_creator_slug"))
    candidates = _string_list(features.get("provider_scoped_candidates"))
    first_candidate = candidates[0] if candidates else ""
    family = _queue_candidate_family(provider, first_candidate)
    candidate_set = set(candidates)

    options: list[dict[str, Any]] = []
    for model_id, canonical_slug, developer_id, alias_norms_text in conn.execute(
        """
        SELECT m.id, m.canonical_slug, m.developer_id,
               GROUP_CONCAT(ma.alias_normalized, ',') AS alias_norms
        FROM model m
        LEFT JOIN model_alias ma ON ma.model_id = m.id
        GROUP BY m.id, m.canonical_slug, m.developer_id
        """
    ):
        canonical_norm = normalize_alias(canonical_slug)
        alias_norms = set(alias_norms_text.split(",")) if alias_norms_text else set()
        score, reason = _queue_option_score(
            provider=provider,
            family=family,
            candidates=candidate_set,
            canonical_norm=canonical_norm,
            alias_norms=alias_norms,
            developer_id=developer_id,
        )
        matched_norms = sorted({canonical_norm, *alias_norms} & candidate_set)
        matched_label = matched_norms[0] if matched_norms else family
        match = f"{reason}: {matched_label} -> {canonical_slug}"
        if score <= 0:
            continue
        options.append(
            {
                "model_id": int(model_id),
                "canonical_slug": canonical_slug,
                "developer_id": developer_id,
                "score": score,
                "match": match,
            }
        )

    options.sort(key=lambda item: (-item["score"], item["canonical_slug"]))
    return {
        "queue_id": int(row[0]),
        "source_record_id": int(row[1]),
        "source_id": row[8],
        "status": row[3],
        "candidate_model_id": row[4],
        "resolved_at": row[5],
        "source_model_id": row[6],
        "model_name": features.get("model_name") or row[7],
        "slug": features.get("slug"),
        "provider": provider,
        "family": family,
        "first_candidate": first_candidate or None,
        "candidate_count": len(candidates),
        "options": options[:limit],
    }

_QUEUE_EXPORT_FIELDS = [
    "queue_id",
    "provider",
    "family",
    "source_model_id",
    "model_name",
    "top_model_id",
    "top_canonical_slug",
    "top_score",
    "top_match",
    "suggested_approval_json",
]

_QUEUE_CANDIDATE_EXPORT_FIELDS = [
    "queue_id",
    "provider",
    "family",
    "source_model_id",
    "model_name",
    "slug",
    "candidate_count",
    "provider_scoped_candidates",
    "existing_candidate_model_ids",
]




def queue_review_export(
    conn: sqlite3.Connection,
    *,
    source_id: str = "artificialanalysis",
    format: str = "csv",
    approval_threshold: int = 80,
    suggested_only: bool = False,
) -> str:
    """Export pending review rows for manual queue approval."""

    rows = _queue_review_rows(conn, source_id=source_id, approval_threshold=approval_threshold)
    if suggested_only:
        rows = [row for row in rows if row["suggested_approval_json"]]
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_QUEUE_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    if format == "markdown":
        lines = [
            "| " + " | ".join(_QUEUE_EXPORT_FIELDS) + " |",
            "| " + " | ".join("---" for _ in _QUEUE_EXPORT_FIELDS) + " |",
        ]
        for row in rows:
            lines.append("| " + " | ".join(_markdown_cell(row[field]) for field in _QUEUE_EXPORT_FIELDS) + " |")
        return "\n".join(lines) + "\n"
    raise ValueError("queue export format must be 'csv' or 'markdown'")

def queue_candidates_export(
    conn: sqlite3.Connection,
    *,
    source_id: str = "artificialanalysis",
    format: str = "csv",
) -> str:
    """Export raw provider-scoped candidates for manual queue review."""

    rows = _queue_candidate_review_rows(conn, source_id=source_id)
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_QUEUE_CANDIDATE_EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
    if format == "markdown":
        lines = [
            "| " + " | ".join(_QUEUE_CANDIDATE_EXPORT_FIELDS) + " |",
            "| " + " | ".join("---" for _ in _QUEUE_CANDIDATE_EXPORT_FIELDS) + " |",
        ]
        for row in rows:
            lines.append("| " + " | ".join(_markdown_cell(row[field]) for field in _QUEUE_CANDIDATE_EXPORT_FIELDS) + " |")
        return "\n".join(lines) + "\n"
    raise ValueError("queue candidates export format must be 'csv' or 'markdown'")


def _queue_candidate_review_rows(conn: sqlite3.Connection, *, source_id: str) -> list[dict[str, str]]:
    existing_model_ids = _existing_model_ids_by_normalized_name(conn)
    rows: list[dict[str, str]] = []
    for queue_id, source_model_id, display_name, features_json in conn.execute(
        """
        SELECT erq.id, smr.source_model_id, smr.display_name, erq.features_json
        FROM entity_resolution_queue erq
        JOIN source_model_record smr ON smr.id = erq.source_record_id
        JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
        WHERE ss.source_id = ?
          AND erq.status = 'pending'
          AND erq.resolved_at IS NULL
          AND erq.candidate_model_id IS NULL
        ORDER BY erq.id
        """,
        (source_id,),
    ):
        features = _loads_json(features_json)
        provider = _text_or_unknown(features.get("model_creator_slug"))
        candidates = _string_list(features.get("provider_scoped_candidates"))
        first_candidate = candidates[0] if candidates else ""
        matched_ids = sorted(
            {
                model_id
                for candidate in candidates
                for model_id in existing_model_ids.get(normalize_alias(candidate), [])
            }
        )
        rows.append(
            {
                "queue_id": str(queue_id),
                "provider": provider,
                "family": _queue_candidate_family(provider, first_candidate),
                "source_model_id": str(source_model_id),
                "model_name": str(features.get("model_name") or display_name),
                "slug": str(features.get("slug") or ""),
                "candidate_count": str(len(candidates)),
                "provider_scoped_candidates": "; ".join(candidates),
                "existing_candidate_model_ids": ",".join(str(model_id) for model_id in matched_ids),
            }
        )
    return rows


def _existing_model_ids_by_normalized_name(conn: sqlite3.Connection) -> dict[str, list[int]]:
    model_ids: dict[str, set[int]] = {}
    for model_id, canonical_slug in conn.execute("SELECT id, canonical_slug FROM model"):
        model_ids.setdefault(normalize_alias(canonical_slug), set()).add(int(model_id))
    for model_id, alias_normalized in conn.execute(
        """
        SELECT model_id, alias_normalized
        FROM model_alias
        WHERE model_id IS NOT NULL
        """
    ):
        model_ids.setdefault(alias_normalized, set()).add(int(model_id))
    return {key: sorted(values) for key, values in model_ids.items()}



def _queue_review_rows(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    approval_threshold: int,
) -> list[dict[str, str]]:
    queue_ids = [
        int(row[0])
        for row in conn.execute(
            """
            SELECT erq.id
            FROM entity_resolution_queue erq
            JOIN source_model_record smr ON smr.id = erq.source_record_id
            JOIN source_snapshot ss ON ss.id = smr.source_snapshot_id
            WHERE ss.source_id = ?
              AND erq.status = 'pending'
              AND erq.resolved_at IS NULL
              AND erq.candidate_model_id IS NULL
            ORDER BY erq.id
            """,
            (source_id,),
        )
    ]
    rows: list[dict[str, str]] = []
    for queue_id in queue_ids:
        payload = queue_candidate_options(conn, queue_id)
        options = payload["options"]
        top = options[0] if options else None
        strong = [option for option in options if int(option["score"]) >= approval_threshold]
        suggested = ""
        if len(strong) == 1:
            suggested = json.dumps(
                {"queue_id": queue_id, "candidate_model_id": strong[0]["model_id"]},
                sort_keys=True,
            )
        rows.append(
            {
                "queue_id": str(queue_id),
                "provider": str(payload["provider"]),
                "family": str(payload["family"]),
                "source_model_id": str(payload["source_model_id"]),
                "model_name": str(payload["model_name"]),
                "top_model_id": str(top["model_id"]) if top else "",
                "top_canonical_slug": str(top["canonical_slug"]) if top else "",
                "top_score": str(top["score"]) if top else "",
                "top_match": str(top["match"]) if top else "",
                "suggested_approval_json": suggested,
            }
        )
    return rows


def _markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")



def _queue_option_score(
    *,
    provider: str,
    family: str,
    candidates: set[str],
    canonical_norm: str,
    alias_norms: set[str],
    developer_id: str | None,
) -> tuple[int, str]:
    provider_match = developer_id == provider
    if not provider_match:
        return (0, "")

    all_norms = {canonical_norm, *alias_norms}
    if all_norms & candidates:
        return (110, "exact_provider_scoped_alias")

    provider_family = f"{provider}-{family}" if provider != "unknown" else family
    if canonical_norm == provider_family or provider_family in alias_norms:
        return (80, "provider_family")
    if canonical_norm.endswith(f"-{family}") or family in alias_norms:
        return (60, "developer_family")
    return (0, "")



def _queue_candidate_family(provider: str, candidate: str) -> str:
    if not candidate:
        return "unknown"
    prefix = f"{provider}-" if provider != "unknown" else ""
    family = candidate.removeprefix(prefix)
    changed = True
    while changed:
        changed = False
        for suffix in _QUEUE_FAMILY_SUFFIXES:
            suffix_token = f"-{suffix}"
            if family.endswith(suffix_token):
                family = family[: -len(suffix_token)]
                changed = True
                break
    return family or "unknown"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text_or_unknown(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "unknown"




def _insert_queue_audit(
    conn: sqlite3.Connection,
    *,
    queue_id: int,
    source_record_id: int,
    candidate_model_id: int | None,
    action: str,
    details: dict[str, Any],
) -> None:
    _ensure_queue_audit_table(conn)
    conn.execute(
        """
        INSERT INTO entity_resolution_audit (
          queue_id, source_record_id, candidate_model_id, action, details_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            queue_id,
            source_record_id,
            candidate_model_id,
            action,
            json.dumps(details, sort_keys=True),
            utcnow(),
        ),
    )


def _ensure_queue_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS entity_resolution_audit (
          id                 INTEGER PRIMARY KEY,
          queue_id           INTEGER NOT NULL REFERENCES entity_resolution_queue(id),
          source_record_id   INTEGER REFERENCES source_model_record(id),
          candidate_model_id INTEGER REFERENCES model(id),
          action             TEXT NOT NULL,
          details_json       TEXT NOT NULL,
          created_at         TEXT NOT NULL
        )
        """
    )


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
    if argv and argv[0] == "drain-accepted":
        if len(argv) > 2 or (len(argv) == 2 and argv[1] != "--dry-run"):
            print("Usage: python -m resolve.resolver drain-accepted [--dry-run]")
            return 2
        dry_run = len(argv) == 2
        with connect() as conn:
            summary = drain_accepted_queue(conn, dry_run=dry_run)
            if not dry_run:
                conn.commit()
        print(json.dumps(summary, sort_keys=True))
        return 0
    if argv and argv[0] == "accept":
        if len(argv) != 3:
            print("Usage: python -m resolve.resolver accept QUEUE_ID MODEL_ID")
            return 2
        with connect() as conn:
            summary = accept_queue_row(conn, queue_id=int(argv[1]), candidate_model_id=int(argv[2]))
            conn.commit()
        print(json.dumps(summary, sort_keys=True))
        return 0
    if argv and argv[0] == "accept-batch":
        if len(argv) >= 2 and argv[1] == "--dry-run":
            if len(argv) != 3:
                print("Usage: python -m resolve.resolver accept-batch [--dry-run] FILE.json")
                return 2
            dry_run = True
            input_path = argv[2]
        elif len(argv) == 2:
            dry_run = False
            input_path = argv[1]
        else:
            print("Usage: python -m resolve.resolver accept-batch [--dry-run] FILE.json")
            return 2
        with open(input_path, encoding="utf-8") as file:
            approvals = json.load(file)
        if not isinstance(approvals, list):
            raise ValueError("accept-batch input must be a JSON array")
        with connect() as conn:
            summary = accept_queue_batch(conn, approvals, dry_run=dry_run)
            if not dry_run:
                conn.commit()
        print(json.dumps(summary, sort_keys=True))
        return 0
    if argv and argv[0] == "accept-new-model-batch":
        if len(argv) >= 2 and argv[1] == "--dry-run":
            if len(argv) != 3:
                print("Usage: python -m resolve.resolver accept-new-model-batch [--dry-run] FILE.json")
                return 2
            dry_run = True
            input_path = argv[2]
        elif len(argv) == 2:
            dry_run = False
            input_path = argv[1]
        else:
            print("Usage: python -m resolve.resolver accept-new-model-batch [--dry-run] FILE.json")
            return 2
        with open(input_path, encoding="utf-8") as file:
            reviews = json.load(file)
        if not isinstance(reviews, list):
            raise ValueError("accept-new-model-batch input must be a JSON array")
        with connect() as conn:
            summary = accept_new_model_batch(conn, reviews, dry_run=dry_run)
            if not dry_run:
                conn.commit()
        print(json.dumps(summary, sort_keys=True))
        return 0
    if argv and argv[0] == "options":
        if len(argv) != 2:
            print("Usage: python -m resolve.resolver options QUEUE_ID")
            return 2
        with connect() as conn:
            options = queue_candidate_options(conn, queue_id=int(argv[1]))
        print(json.dumps(options, sort_keys=True))
        return 0
    if argv and argv[0] == "queue-export":
        export_format = "csv"
        suggested_only = False
        args = argv[1:]
        if "--suggested-only" in args:
            suggested_only = True
            args = [arg for arg in args if arg != "--suggested-only"]
        if args[:2] == ["--format", "markdown"]:
            export_format = "markdown"
            args = args[2:]
        elif args[:2] == ["--format", "csv"]:
            args = args[2:]
        if len(args) > 1:
            print("Usage: python -m resolve.resolver queue-export [--format csv|markdown] [--suggested-only] [source_id]")
            return 2
        source_id = args[0] if args else "artificialanalysis"
        with connect() as conn:
            export = queue_review_export(
                conn,
                source_id=source_id,
                format=export_format,
                suggested_only=suggested_only,
            )
        print(export, end="")
        return 0
    if argv and argv[0] == "queue-candidates-export":
        export_format = "csv"
        args = argv[1:]
        if args[:2] == ["--format", "markdown"]:
            export_format = "markdown"
            args = args[2:]
        elif args[:2] == ["--format", "csv"]:
            args = args[2:]
        if len(args) > 1:
            print("Usage: python -m resolve.resolver queue-candidates-export [--format csv|markdown] [source_id]")
            return 2
        source_id = args[0] if args else "artificialanalysis"
        with connect() as conn:
            export = queue_candidates_export(conn, source_id=source_id, format=export_format)
        print(export, end="")
        return 0
    if argv and argv[0] == "queue-report":
        if len(argv) > 2:
            print("Usage: python -m resolve.resolver queue-report [source_id]")
            return 2
        source_id = argv[1] if len(argv) == 2 else "artificialanalysis"
        with connect() as conn:
            report = pending_queue_report(conn, source_id=source_id)
        print(json.dumps(report, sort_keys=True))
        return 0
    if len(argv) != 1:
        print("Usage: python -m resolve.resolver SOURCE_MODEL_RECORD_ID")
        print("       python -m resolve.resolver accept QUEUE_ID MODEL_ID")
        print("       python -m resolve.resolver accept-batch [--dry-run] FILE.json")
        print("       python -m resolve.resolver accept-new-model-batch [--dry-run] FILE.json")
        print("       python -m resolve.resolver drain-accepted [--dry-run]")
        print("       python -m resolve.resolver options QUEUE_ID")
        print("       python -m resolve.resolver queue-export [--format csv|markdown] [--suggested-only] [source_id]")
        print("       python -m resolve.resolver queue-candidates-export [--format csv|markdown] [source_id]")
        print("       python -m resolve.resolver queue-report [source_id]")
        return 2
    with connect() as conn:
        alias_id = resolve_record(conn, int(argv[0]))
        conn.commit()
    print(f"resolved alias_id={alias_id}" if alias_id is not None else "queued for review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
