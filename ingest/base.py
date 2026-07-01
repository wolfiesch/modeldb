"""Parser interface + shared ingest plumbing.

Every source parser subclasses `SourceParser` and implements `fetch()` and `parse()`.
The driver (`ingest/run.py`) handles snapshotting, hashing, and raw persistence so
individual parsers stay small and deterministic.

Contract:
  - fetch() returns the raw bytes/text exactly as the source served them.
  - parse(raw, snapshot_id) yields SourceModelRecord rows. It MUST NOT invent canonical
    model ids; it only emits source-native ids + parsed fields. Resolution happens later.
  - Parsers are pure w.r.t. the DB except for writing source_model_record rows via the
    helper. No canonical-table writes from a parser.
"""
from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "modeldb.sqlite"
RAW_ROOT = REPO_ROOT / "data" / "raw"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclasses.dataclass
class SourceModelRecord:
    """One model as a single source sees it. Pre-resolution."""
    source_model_id: str
    display_name: Optional[str] = None
    provider_name: Optional[str] = None
    raw_record_json: str = "{}"
    parsed_fields_json: Optional[str] = None


class SourceParser:
    """Subclass per source. See ingest/PARSER_GUIDE.md."""

    source_id: str = ""           # must match a row in `source`
    parser_version: str = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        """Return (url, raw_bytes, http_meta). http_meta may carry etag/last_modified.

        Stub parsers raise NotImplementedError; implement in milestone M1+.
        """
        raise NotImplementedError

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Yield SourceModelRecord rows from raw bytes."""
        raise NotImplementedError

    # -- shared plumbing -----------------------------------------------------

    def snapshot(self, conn: sqlite3.Connection, url: str, raw: bytes, http_meta: dict) -> int:
        """Persist raw body + record a source_snapshot. Idempotent on content hash."""
        digest = sha256(raw)
        existing = conn.execute(
            "SELECT id FROM source_snapshot WHERE source_id=? AND url=? AND content_hash=?",
            (self.source_id, url, digest),
        ).fetchone()
        if existing:
            return existing[0]

        ts = utcnow()
        raw_dir = RAW_ROOT / self.source_id
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{ts.replace(':', '').replace('-', '')}_{digest[:8]}.raw"
        raw_path.write_bytes(raw)

        cur = conn.execute(
            """INSERT INTO source_snapshot
                 (source_id, url, fetched_at, content_hash, etag, last_modified, parser_version, raw_path)
               VALUES (?,?,?,?,?,?,?,?)""",
            (self.source_id, url, ts, digest, http_meta.get("etag"),
             http_meta.get("last_modified"), self.parser_version,
             str(raw_path.relative_to(REPO_ROOT))),
        )
        conn.commit()
        return cur.lastrowid

    def store_records(self, conn: sqlite3.Connection, snapshot_id: int,
                      records: Iterable[SourceModelRecord]) -> int:
        n = 0
        for r in records:
            conn.execute(
                """INSERT OR REPLACE INTO source_model_record
                     (source_snapshot_id, source_model_id, display_name, provider_name,
                      raw_record_json, parsed_fields_json)
                   VALUES (?,?,?,?,?,?)""",
                (snapshot_id, r.source_model_id, r.display_name, r.provider_name,
                 r.raw_record_json, r.parsed_fields_json),
            )
            n += 1
        conn.commit()
        return n

    def run(self, conn: sqlite3.Connection) -> dict:
        """fetch → snapshot → parse → store. Returns a summary dict."""
        url, raw, http_meta = self.fetch()
        snap = self.snapshot(conn, url, raw, http_meta)
        n = self.store_records(conn, snap, self.parse(raw, snap))
        return {"source": self.source_id, "snapshot_id": snap, "records": n}


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
