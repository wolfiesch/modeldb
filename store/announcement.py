"""Preserve a launch announcement as durable provider_blog evidence.

Launch pages report headline benchmark numbers only as chart IMAGES, so we do NOT
fabricate benchmark_result rows from them (see new-model-drop research rule). We
persist the textually-confirmed facts as a source_snapshot + raw file and attach a
display-name alias to the canonical model. Numeric benchmarks await the system-card
PDF or independent aggregators (Epoch/LMArena) and are added later with provenance.

Idempotent: re-running with the same evidence dict is a no-op (content hash).

Usage:
    python -m store.announcement            # captures the bundled Sonnet 5 evidence
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ingest.base import REPO_ROOT, connect, utcnow
from resolve.normalize import normalize_alias

# Textually-confirmed facts from https://www.anthropic.com/news/claude-sonnet-5
# (2026-06-30). Benchmark NUMBERS intentionally excluded: image-only on the page.
SONNET5_EVIDENCE = {
    "canonical_slug": "anthropic/claude-sonnet-5",
    "display_name": "Claude Sonnet 5",
    "source_url": "https://www.anthropic.com/news/claude-sonnet-5",
    "release_date": "2026-06-30",
    "positioning": "most agentic Sonnet yet; performance close to Opus 4.8 at lower "
                   "price; improvement over Sonnet 4.6 on reasoning/tool-use/coding.",
    "pricing_intro": {"input_per_1m": 2, "output_per_1m": 10, "through": "2026-08-31"},
    "pricing_standard": {"input_per_1m": 3, "output_per_1m": 15},
    "tokenizer_change": "updated tokenizer; same input maps to ~1.0-1.35x more tokens "
                        "vs Sonnet 4.6.",
    "named_benchmarks_image_only": ["BrowseComp", "OSWorld-Verified",
                                    "Humanity's Last Exam (HLE)"],
    "benchmark_numbers": "NOT captured: reported only as chart images. Await the "
                         "Sonnet 5 System Card PDF or independent aggregators.",
    "system_card_url": "https://www.anthropic.com/claude-sonnet-5-system-card",
    "cyber_safeguards": "enabled by default (Cyber Verification Program).",
}


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


if __name__ == "__main__":
    with connect() as c:
        print(capture_announcement(c, SONNET5_EVIDENCE))
