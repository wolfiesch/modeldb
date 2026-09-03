"""Preserve a launch announcement as durable provider_blog evidence.

Launch pages report headline benchmark numbers only as chart IMAGES, so we do NOT
fabricate benchmark_result rows from them (see new-model-drop research rule). We
persist the textually-confirmed facts as a source_snapshot + raw file and attach a
display-name alias to the canonical model. Numeric benchmarks await the system-card
PDF or independent aggregators (Epoch/LMArena) and are added later with provenance.

Idempotent: re-running with the same evidence dict is a no-op (content hash).

The curated launch set that calls this lives in `store.launch_registry`.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

from ingest.base import REPO_ROOT, utcnow
from resolve.normalize import normalize_alias


def capture_announcement(conn: sqlite3.Connection, evidence: dict) -> dict:
    now = utcnow()
    url = evidence["source_url"]
    raw = json.dumps(evidence, sort_keys=True).encode()
    digest = hashlib.sha256(raw).hexdigest()

    existing = conn.execute(
        "SELECT id FROM source_snapshot WHERE source_id='provider_blog' AND url=? AND content_hash=?",
        (url, digest),
    ).fetchone()
    if existing:
        return {"snapshot_id": existing[0], "created": False}

    raw_dir = REPO_ROOT / "data" / "raw" / "provider_blog"
    raw_dir.mkdir(parents=True, exist_ok=True)
    slug_safe = evidence["canonical_slug"].replace("/", "_")
    raw_path = raw_dir / f"{slug_safe}_{digest[:8]}.json"
    raw_path.write_bytes(raw)

    cur = conn.execute(
        """INSERT INTO source_snapshot (source_id, url, fetched_at, content_hash, parser_version, raw_path)
           VALUES ('provider_blog', ?, ?, ?, 'manual-0.1', ?)""",
        (url, now, digest, str(raw_path.relative_to(REPO_ROOT))),
    )
    snap = cur.lastrowid

    row = conn.execute(
        "SELECT id FROM model WHERE canonical_slug=?", (evidence["canonical_slug"],)
    ).fetchone()
    if row:
        disp = evidence["display_name"]
        conn.execute(
            """INSERT OR IGNORE INTO model_alias
                 (source_id, alias_string, alias_normalized, alias_kind, model_id,
                  resolution_method, confidence, source_snapshot_id, first_seen_at, last_seen_at)
               VALUES ('provider_blog', ?, ?, 'display_name', ?, 'exact_provider_doc', 1.0, ?, ?, ?)""",
            (disp, normalize_alias(disp), row[0], snap, now, now),
        )
    conn.commit()
    return {"snapshot_id": snap, "created": True, "model_linked": bool(row)}


