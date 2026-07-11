from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import apply_queue_approvals


class ApplyQueueApprovalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.workdir = Path(self.tmpdir.name)
        self.db_path = self.workdir / "models.sqlite"
        self.approvals_path = self.workdir / "approvals.json"
        self.queue_id = self._create_fixture_db(self.db_path)

    def test_valid_approvals_backup_then_dry_run_accept_and_drain_before_pipeline_is_skipped(self) -> None:
        self._write_approvals([{"queue_id": self.queue_id, "candidate_model_id": 1}])

        summary = apply_queue_approvals.apply_queue_approvals(
            self.approvals_path,
            db_path=self.db_path,
            backup_dir=self.workdir / "backups",
            run_pipeline=False,
            backup_label="valid",
        )

        backup_path = Path(summary["backup_path"])
        self.assertTrue(backup_path.exists())
        self.assertNotEqual(backup_path.resolve(), self.db_path.resolve())
        self.assertEqual(self._queue_states(backup_path), [(self.queue_id, None, "pending", None)])
        self.assertEqual(self._alias_rows(backup_path), [])
        self.assertEqual(self._source_links(backup_path), [(101, None)])
        self.assertEqual(self._audit_actions(backup_path), [])

        self.assertEqual(summary["approval_count"], 1)
        self.assertEqual(summary["accept_dry_run"]["accepted"], 1)
        self.assertIs(summary["accept_dry_run"]["dry_run"], True)
        self.assertEqual(summary["accept"]["accepted"], 1)
        self.assertIs(summary["accept"]["dry_run"], False)
        self.assertEqual(summary["drain_dry_run"]["processed"], 1)
        self.assertIs(summary["drain_dry_run"]["dry_run"], True)
        self.assertEqual(summary["drain"]["processed"], 1)
        self.assertIs(summary["drain"]["dry_run"], False)
        self.assertEqual(summary["pipeline"], {"run": False, "reason": "disabled"})

        status, resolved_at = self._queue_states(self.db_path)[0][2:]
        self.assertEqual(status, "accepted")
        self.assertIsNotNone(resolved_at)
        self.assertEqual(
            self._alias_rows(self.db_path),
            [("alibaba-qwen3-5-omni-plus", "api_model_id", 1, "artificialanalysis", 201)],
        )
        self.assertEqual(self._source_links(self.db_path), [(101, 1)])
        self.assertEqual(self._audit_actions(self.db_path), ["accept", "drain"])

    def test_invalid_approvals_raise_and_leave_database_unmutated(self) -> None:
        self._write_approvals([{"queue_id": self.queue_id, "candidate_model_id": 999}])
        before = self._database_state(self.db_path)

        with self.assertRaises(ValueError):
            apply_queue_approvals.apply_queue_approvals(
                self.approvals_path,
                db_path=self.db_path,
                backup_dir=self.workdir / "backups",
                run_pipeline=False,
                backup_label="invalid",
            )

        self.assertEqual(self._database_state(self.db_path), before)
        for backup_path in (self.workdir / "backups").glob("*.sqlite"):
            self.assertEqual(self._database_state(backup_path), before)

    def test_cli_skip_pipeline_prints_json_summary(self) -> None:
        self._write_approvals([{"queue_id": self.queue_id, "candidate_model_id": 1}])
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            exit_code = apply_queue_approvals.main(
                [
                    "--db",
                    str(self.db_path),
                    "--backup-dir",
                    str(self.workdir / "cli-backups"),
                    "--skip-pipeline",
                    str(self.approvals_path),
                ]
            )

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["approval_count"], 1)
        self.assertEqual(payload["accept"]["accepted"], 1)
        self.assertEqual(payload["drain"]["processed"], 1)
        self.assertEqual(payload["pipeline"], {"run": False, "reason": "disabled"})
        self.assertTrue(Path(payload["backup_path"]).exists())
        self.assertEqual(self._audit_actions(self.db_path), ["accept", "drain"])

    def _create_fixture_db(self, db_path: Path) -> int:
        with closing(sqlite3.connect(db_path)) as conn:
            conn.executescript(
                """
                CREATE TABLE source_snapshot (
                    id INTEGER PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    url TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    parser_version TEXT NOT NULL,
                    raw_path TEXT
                );
                CREATE TABLE source_model_record (
                    id INTEGER PRIMARY KEY,
                    source_snapshot_id INTEGER NOT NULL,
                    source_model_id TEXT NOT NULL,
                    display_name TEXT,
                    provider_name TEXT,
                    raw_record_json TEXT NOT NULL,
                    parsed_fields_json TEXT,
                    model_alias_id INTEGER
                );
                CREATE TABLE model (
                    id INTEGER PRIMARY KEY,
                    canonical_slug TEXT NOT NULL,
                    developer_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE model_alias (
                    id INTEGER PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    alias_string TEXT NOT NULL,
                    alias_normalized TEXT NOT NULL,
                    alias_kind TEXT NOT NULL,
                    model_id INTEGER,
                    provider_surface_id INTEGER,
                    artifact_id INTEGER,
                    valid_from TEXT,
                    valid_to TEXT,
                    resolution_method TEXT,
                    confidence REAL NOT NULL,
                    source_snapshot_id INTEGER,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX idx_alias_unique
                    ON model_alias (source_id, alias_string, alias_kind, COALESCE(valid_from, ''));
                CREATE TABLE entity_resolution_queue (
                    id INTEGER PRIMARY KEY,
                    source_record_id INTEGER,
                    candidate_model_id INTEGER,
                    reason TEXT NOT NULL,
                    features_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );

                INSERT INTO model (id, canonical_slug, developer_id, created_at, updated_at)
                VALUES (1, 'alibaba/qwen3.5-omni-plus', 'alibaba', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
                INSERT INTO source_snapshot (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
                VALUES (201, 'artificialanalysis', 'memory://artificialanalysis', '2026-01-02T00:00:00Z', 'hash-201', 'test', NULL);
                INSERT INTO source_model_record
                    (id, source_snapshot_id, source_model_id, display_name, provider_name, raw_record_json, parsed_fields_json)
                VALUES (101, 201, 'qwen3-5-omni-plus', 'Qwen3.5 Omni Plus', 'Alibaba', '{}', '{}');
                """
            )
            cursor = conn.execute(
                """
                INSERT INTO entity_resolution_queue
                    (source_record_id, candidate_model_id, reason, features_json, status, created_at)
                VALUES (101, NULL, 'manual approval wrapper fixture', ?, 'pending', '2026-01-02T00:00:00Z')
                """,
                (json.dumps({"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]}, sort_keys=True),),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def _write_approvals(self, approvals: list[dict[str, int]]) -> None:
        self.approvals_path.write_text(json.dumps(approvals), encoding="utf-8")

    def _database_state(self, db_path: Path) -> dict[str, object]:
        return {
            "queue": self._queue_states(db_path),
            "aliases": self._alias_rows(db_path),
            "source_links": self._source_links(db_path),
            "audit_actions": self._audit_actions(db_path),
        }

    def _queue_states(self, db_path: Path) -> list[tuple[object, ...]]:
        with closing(sqlite3.connect(db_path)) as conn:
            return conn.execute(
                """
                SELECT id, candidate_model_id, status, resolved_at
                FROM entity_resolution_queue
                ORDER BY id
                """
            ).fetchall()

    def _alias_rows(self, db_path: Path) -> list[tuple[object, ...]]:
        with closing(sqlite3.connect(db_path)) as conn:
            return conn.execute(
                """
                SELECT alias_string, alias_kind, model_id, source_id, source_snapshot_id
                FROM model_alias
                ORDER BY id
                """
            ).fetchall()

    def _source_links(self, db_path: Path) -> list[tuple[object, ...]]:
        with closing(sqlite3.connect(db_path)) as conn:
            return conn.execute(
                """
                SELECT id, model_alias_id
                FROM source_model_record
                ORDER BY id
                """
            ).fetchall()

    def _audit_actions(self, db_path: Path) -> list[str]:
        with closing(sqlite3.connect(db_path)) as conn:
            if not self._table_exists(conn, "entity_resolution_audit"):
                return []
            return [
                row[0]
                for row in conn.execute(
                    """
                    SELECT action
                    FROM entity_resolution_audit
                    ORDER BY id
                    """
                ).fetchall()
            ]

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        return (
            conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (table_name,),
            ).fetchone()
            is not None
        )


if __name__ == "__main__":
    unittest.main()
