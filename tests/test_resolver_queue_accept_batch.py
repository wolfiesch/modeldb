from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


class AcceptQueueBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = self._new_connection()
        self.addCleanup(self.conn.close)

    def test_accepts_multiple_pending_rows_atomically_and_audits_each_approval(self) -> None:
        first_queue_id = self._insert_queue_row(
            source_record_id=101,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        second_queue_id = self._insert_queue_row(
            source_record_id=102,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        self.assertFalse(self._table_exists("entity_resolution_audit"))

        summary = resolver.accept_queue_batch(
            self.conn,
            [
                {"queue_id": first_queue_id, "candidate_model_id": 1},
                {"queue_id": second_queue_id, "candidate_model_id": 2},
            ],
        )

        self.assertEqual(summary["accepted"], 2)
        self.assertEqual(
            [(item["queue_id"], item["candidate_model_id"]) for item in summary["items"]],
            [(first_queue_id, 1), (second_queue_id, 2)],
        )
        self.assertEqual(
            self._queue_states(),
            [
                (first_queue_id, 101, 1, "accepted", None),
                (second_queue_id, 102, 2, "accepted", None),
            ],
        )
        rows = self._audit_rows()
        self.assertEqual(
            [(row["action"], row["queue_id"], row["source_record_id"], row["candidate_model_id"]) for row in rows],
            [
                ("accept", first_queue_id, 101, 1),
                ("accept", second_queue_id, 102, 2),
            ],
        )
        self.assertEqual(
            [json.loads(row["details_json"]) for row in rows],
            [
                {
                    "prior_status": "pending",
                    "prior_candidate_model_id": None,
                    "prior_resolved_at": None,
                },
                {
                    "prior_status": "pending",
                    "prior_candidate_model_id": None,
                    "prior_resolved_at": None,
                },
            ],
        )


    def test_dry_run_reports_accepted_items_without_mutating_queue_or_audit(self) -> None:
        first_queue_id = self._insert_queue_row(
            source_record_id=101,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        second_queue_id = self._insert_queue_row(
            source_record_id=102,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        approvals = [
            {"queue_id": first_queue_id, "candidate_model_id": 1},
            {"queue_id": second_queue_id, "candidate_model_id": 2},
        ]
        before_rows = self._queue_states()
        self.assertFalse(self._table_exists("entity_resolution_audit"))

        summary = resolver.accept_queue_batch(self.conn, approvals, dry_run=True)

        self.assertEqual(summary["accepted"], 2)
        self.assertIs(summary["dry_run"], True)
        self.assertEqual(
            [(item["queue_id"], item["candidate_model_id"]) for item in summary["items"]],
            [(first_queue_id, 1), (second_queue_id, 2)],
        )
        self.assertEqual(self._queue_states(), before_rows)
        self.assertEqual(self._audit_count_or_zero(), 0)

    def test_real_batch_after_dry_run_still_applies_approvals_and_audit_rows(self) -> None:
        first_queue_id = self._insert_queue_row(
            source_record_id=101,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        second_queue_id = self._insert_queue_row(
            source_record_id=102,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        approvals = [
            {"queue_id": first_queue_id, "candidate_model_id": 1},
            {"queue_id": second_queue_id, "candidate_model_id": 2},
        ]

        dry_run_summary = resolver.accept_queue_batch(self.conn, approvals, dry_run=True)
        real_summary = resolver.accept_queue_batch(self.conn, approvals)

        self.assertEqual(dry_run_summary["accepted"], 2)
        self.assertIs(dry_run_summary["dry_run"], True)
        self.assertEqual(real_summary["accepted"], 2)
        self.assertEqual(
            self._queue_states(),
            [
                (first_queue_id, 101, 1, "accepted", None),
                (second_queue_id, 102, 2, "accepted", None),
            ],
        )
        self.assertEqual(
            [(row["action"], row["queue_id"], row["candidate_model_id"]) for row in self._audit_rows()],
            [("accept", first_queue_id, 1), ("accept", second_queue_id, 2)],
        )

    def test_invalid_dry_run_leaves_all_queue_rows_and_audit_unchanged(self) -> None:
        valid_queue_id = self._insert_queue_row(
            source_record_id=101,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        invalid_queue_id = self._insert_queue_row(
            source_record_id=102,
            status="accepted",
            candidate_model_id=2,
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        before_rows = self._queue_states()
        self.assertFalse(self._table_exists("entity_resolution_audit"))

        with self.assertRaises(ValueError):
            resolver.accept_queue_batch(
                self.conn,
                [
                    {"queue_id": valid_queue_id, "candidate_model_id": 1},
                    {"queue_id": invalid_queue_id, "candidate_model_id": 2},
                ],
                dry_run=True,
            )

        self.assertEqual(self._queue_states(), before_rows)
        self.assertEqual(self._audit_count_or_zero(), 0)

    def test_invalid_approval_leaves_all_queue_rows_and_audit_unchanged(self) -> None:
        for name, invalid_row, invalid_model_id in [
            ("unknown model id", {"status": "pending", "candidate_model_id": None}, 999),
            ("non-pending queue row", {"status": "accepted", "candidate_model_id": 1}, 2),
        ]:
            with self.subTest(name=name):
                conn = self._new_connection()
                self.addCleanup(conn.close)
                valid_queue_id = self._insert_queue_row(
                    conn=conn,
                    source_record_id=101,
                    status="pending",
                    candidate_model_id=None,
                    features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
                )
                invalid_queue_id = self._insert_queue_row(
                    conn=conn,
                    source_record_id=102,
                    status=invalid_row["status"],
                    candidate_model_id=invalid_row["candidate_model_id"],
                    features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
                )
                before_rows = self._queue_states(conn=conn)
                self.assertFalse(self._table_exists("entity_resolution_audit", conn=conn))

                with self.assertRaises(ValueError):
                    resolver.accept_queue_batch(
                        conn,
                        [
                            {"queue_id": valid_queue_id, "candidate_model_id": 1},
                            {"queue_id": invalid_queue_id, "candidate_model_id": invalid_model_id},
                        ],
                    )

                self.assertEqual(self._queue_states(conn=conn), before_rows)
                self.assertFalse(self._table_exists("entity_resolution_audit", conn=conn))

    def test_accept_batch_cli_reads_json_file_prints_summary_and_applies_approvals(self) -> None:
        first_queue_id = self._insert_queue_row(
            source_record_id=101,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        second_queue_id = self._insert_queue_row(
            source_record_id=102,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        approvals = [
            {"queue_id": first_queue_id, "candidate_model_id": 1},
            {"queue_id": second_queue_id, "candidate_model_id": 2},
        ]
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "approvals.json"
            path.write_text(json.dumps(approvals), encoding="utf-8")
            with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
                with redirect_stdout(stdout):
                    exit_code = resolver.main(["accept-batch", str(path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["accepted"], 2)
        self.assertEqual(
            [(item["queue_id"], item["candidate_model_id"]) for item in payload["items"]],
            [(first_queue_id, 1), (second_queue_id, 2)],
        )
        self.assertEqual(
            self._queue_states(),
            [
                (first_queue_id, 101, 1, "accepted", None),
                (second_queue_id, 102, 2, "accepted", None),
            ],
        )
        self.assertEqual(
            [(row["action"], row["queue_id"], row["candidate_model_id"]) for row in self._audit_rows()],
            [("accept", first_queue_id, 1), ("accept", second_queue_id, 2)],
        )

    def test_accept_batch_dry_run_cli_reads_json_file_prints_summary_without_mutation(self) -> None:
        first_queue_id = self._insert_queue_row(
            source_record_id=101,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        second_queue_id = self._insert_queue_row(
            source_record_id=102,
            status="pending",
            candidate_model_id=None,
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        approvals = [
            {"queue_id": first_queue_id, "candidate_model_id": 1},
            {"queue_id": second_queue_id, "candidate_model_id": 2},
        ]
        before_rows = self._queue_states()
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "approvals.json"
            path.write_text(json.dumps(approvals), encoding="utf-8")
            with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
                with redirect_stdout(stdout):
                    exit_code = resolver.main(["accept-batch", "--dry-run", str(path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["accepted"], 2)
        self.assertIs(payload["dry_run"], True)
        self.assertEqual(
            [(item["queue_id"], item["candidate_model_id"]) for item in payload["items"]],
            [(first_queue_id, 1), (second_queue_id, 2)],
        )
        self.assertEqual(self._queue_states(), before_rows)
        self.assertEqual(self._audit_count_or_zero(), 0)


    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE model (
                id INTEGER PRIMARY KEY,
                canonical_slug TEXT NOT NULL,
                developer_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE source_model_record (
                id INTEGER PRIMARY KEY,
                source_snapshot_id INTEGER,
                source_model_id TEXT NOT NULL,
                display_name TEXT,
                provider_name TEXT,
                raw_record_json TEXT NOT NULL,
                parsed_fields_json TEXT,
                model_alias_id INTEGER
            );
            CREATE TABLE entity_resolution_queue (
                id INTEGER PRIMARY KEY,
                source_record_id INTEGER,
                candidate_model_id INTEGER,
                reason TEXT NOT NULL,
                features_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            INSERT INTO model (id, canonical_slug, developer_id, created_at, updated_at)
            VALUES
                (1, 'alibaba/qwen3.5-omni-plus', 'alibaba', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (2, 'anthropic/claude-opus-4', 'anthropic', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00');

            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name, raw_record_json, parsed_fields_json)
            VALUES
                (101, 201, 'qwen3-5-omni-plus', 'Qwen3.5 Omni Plus', 'Alibaba', '{}', '{}'),
                (102, 202, 'claude-opus-4', 'Claude Opus 4', 'Anthropic', '{}', '{}');
            """
        )
        return conn

    def _insert_queue_row(
        self,
        *,
        source_record_id: int,
        status: str,
        candidate_model_id: int | None,
        features: dict[str, object],
        conn: sqlite3.Connection | None = None,
    ) -> int:
        target = self.conn if conn is None else conn
        cursor = target.execute(
            """
            INSERT INTO entity_resolution_queue
                (source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (?, ?, 'manual batch accept fixture', ?, ?, '2026-07-02T19:00:00+00:00', NULL)
            """,
            (source_record_id, candidate_model_id, json.dumps(features, sort_keys=True), status),
        )
        return int(cursor.lastrowid)

    def _queue_states(self, *, conn: sqlite3.Connection | None = None) -> list[tuple[object, ...]]:
        target = self.conn if conn is None else conn
        return target.execute(
            """
            SELECT id, source_record_id, candidate_model_id, status, resolved_at
            FROM entity_resolution_queue
            ORDER BY id
            """
        ).fetchall()

    def _table_exists(self, table_name: str, *, conn: sqlite3.Connection | None = None) -> bool:
        target = self.conn if conn is None else conn
        return (
            target.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (table_name,),
            ).fetchone()
            is not None
        )

    def _audit_count_or_zero(self, *, conn: sqlite3.Connection | None = None) -> int:
        if not self._table_exists("entity_resolution_audit", conn=conn):
            return 0
        target = self.conn if conn is None else conn
        return int(target.execute("SELECT COUNT(*) FROM entity_resolution_audit").fetchone()[0])

    def _audit_rows(self) -> list[sqlite3.Row]:
        old_factory = self.conn.row_factory
        self.conn.row_factory = sqlite3.Row
        try:
            return self.conn.execute(
                """
                SELECT action, queue_id, source_record_id, candidate_model_id, details_json
                FROM entity_resolution_audit
                ORDER BY id
                """
            ).fetchall()
        finally:
            self.conn.row_factory = old_factory


class _ExistingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
