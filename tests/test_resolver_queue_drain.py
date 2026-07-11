from __future__ import annotations

import io
import json
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


class DrainAcceptedQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
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
            """
        )

    def test_accepted_queue_row_creates_provider_scoped_aliases_and_resolves_source_record(self) -> None:
        source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={
                "provider_scoped_candidates": [
                    "alibaba-qwen3-5-omni-plus",
                    "alibaba-qwen3-5-omni-plus-preview",
                ]
            },
        )

        resolver.drain_accepted_queue(self.conn)

        aliases = self.conn.execute(
            """
            SELECT id, alias_string, alias_kind, model_id, source_id, source_snapshot_id
            FROM model_alias
            ORDER BY alias_string
            """
        ).fetchall()
        self.assertEqual(
            [(row[1], row[2], row[3], row[4], row[5]) for row in aliases],
            [
                ("alibaba-qwen3-5-omni-plus", "api_model_id", 1, "artificialanalysis", 100),
                ("alibaba-qwen3-5-omni-plus-preview", "api_model_id", 1, "artificialanalysis", 100),
            ],
        )

        linked_alias_id = self.conn.execute(
            "SELECT model_alias_id FROM source_model_record WHERE id = ?",
            (source_record_id,),
        ).fetchone()[0]
        self.assertIn(linked_alias_id, {row[0] for row in aliases})

        status, resolved_at = self.conn.execute(
            "SELECT status, resolved_at FROM entity_resolution_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()
        self.assertNotEqual(status, "pending")
        self.assertIsNotNone(resolved_at)

    def test_dry_run_reports_accepted_row_without_mutating_aliases_queue_or_audit(self) -> None:
        source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={
                "provider_scoped_candidates": [
                    "alibaba-qwen3-5-omni-plus",
                    "alibaba-qwen3-5-omni-plus-preview",
                ]
            },
        )

        summary = resolver.drain_accepted_queue(self.conn, dry_run=True)

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["aliases_upserted"], 2)
        self.assertEqual(summary["records_updated"], 1)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(self._alias_count(), 0)
        self.assertIsNone(self._linked_alias_id(source_record_id))
        self.assertEqual(self._queue_state(queue_id), ("accepted", None))
        self.assertEqual(self._audit_count(), 0)

    def test_real_drain_after_dry_run_materializes_aliases_source_link_resolved_at_and_audit(
        self,
    ) -> None:
        source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={
                "provider_scoped_candidates": [
                    "alibaba-qwen3-5-omni-plus",
                    "alibaba-qwen3-5-omni-plus-preview",
                ]
            },
        )

        dry_run_summary = resolver.drain_accepted_queue(self.conn, dry_run=True)
        real_summary = resolver.drain_accepted_queue(self.conn)

        self.assertEqual(dry_run_summary["processed"], 1)
        self.assertEqual(dry_run_summary["aliases_upserted"], 2)
        self.assertEqual(real_summary["processed"], 1)
        self.assertEqual(real_summary["aliases_upserted"], 2)
        aliases = self.conn.execute(
            """
            SELECT id, alias_string, model_id
            FROM model_alias
            ORDER BY alias_string
            """
        ).fetchall()
        self.assertEqual(
            [(row[1], row[2]) for row in aliases],
            [
                ("alibaba-qwen3-5-omni-plus", 1),
                ("alibaba-qwen3-5-omni-plus-preview", 1),
            ],
        )
        self.assertIn(self._linked_alias_id(source_record_id), {row[0] for row in aliases})
        status, resolved_at = self._queue_state(queue_id)
        self.assertEqual(status, "accepted")
        self.assertIsNotNone(resolved_at)
        self.assertEqual(self._audit_count(), 1)

    def test_drain_accepted_dry_run_cli_prints_json_summary_without_mutation(self) -> None:
        source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={
                "provider_scoped_candidates": [
                    "alibaba-qwen3-5-omni-plus",
                    "alibaba-qwen3-5-omni-plus-preview",
                ]
            },
        )
        stdout = io.StringIO()

        with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
            with redirect_stdout(stdout):
                exit_code = resolver.main(["drain-accepted", "--dry-run"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(payload["aliases_upserted"], 2)
        self.assertEqual(payload["records_updated"], 1)
        self.assertEqual(payload["skipped"], 0)
        self.assertEqual(self._alias_count(), 0)
        self.assertIsNone(self._linked_alias_id(source_record_id))
        self.assertEqual(self._queue_state(queue_id), ("accepted", None))
        self.assertEqual(self._audit_count(), 0)


    def test_drain_accepted_cli_queue_id_scopes_non_dry_run_to_one_accepted_row(self) -> None:
        target_source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        target_queue_id = self._insert_queue_row(
            source_record_id=target_source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        unrelated_source_record_id = self._insert_source_record("qwen3-5-omni-plus-unrelated")
        unrelated_queue_id = self._insert_queue_row(
            source_record_id=unrelated_source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus-unrelated"]},
        )
        stdout = io.StringIO()

        with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
            with redirect_stdout(stdout):
                exit_code = resolver.main(["drain-accepted", "--queue-id", str(target_queue_id)])

        self.assertEqual(exit_code, 0, stdout.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(payload["aliases_upserted"], 1)
        self.assertEqual(payload["records_updated"], 1)
        self.assertEqual(payload["skipped"], 0)
        self.assertEqual(self._queue_state(target_queue_id)[0], "accepted")
        self.assertIsNotNone(self._queue_state(target_queue_id)[1])
        self.assertEqual(self._queue_state(unrelated_queue_id), ("accepted", None))
        self.assertIsNotNone(self._linked_alias_id(target_source_record_id))
        self.assertIsNone(self._linked_alias_id(unrelated_source_record_id))
        aliases = self.conn.execute("SELECT alias_string FROM model_alias ORDER BY alias_string").fetchall()
        self.assertEqual([row[0] for row in aliases], ["alibaba-qwen3-5-omni-plus"])

    def test_accepted_queue_row_without_candidate_model_is_skipped_without_creating_alias(self) -> None:
        source_record_id = self._insert_source_record("unknown-qwen")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=None,
            status="accepted",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )

        resolver.drain_accepted_queue(self.conn)

        self.assertEqual(self._alias_count(), 0)
        self.assertIsNone(self._linked_alias_id(source_record_id))
        resolved_at = self.conn.execute(
            "SELECT resolved_at FROM entity_resolution_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()[0]
        self.assertIsNone(resolved_at)

    def test_pending_queue_row_with_candidate_model_is_skipped(self) -> None:
        source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=1,
            status="pending",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )

        resolver.drain_accepted_queue(self.conn)

        self.assertEqual(self._alias_count(), 0)
        self.assertIsNone(self._linked_alias_id(source_record_id))
        status, resolved_at = self.conn.execute(
            "SELECT status, resolved_at FROM entity_resolution_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()
        self.assertEqual(status, "pending")
        self.assertIsNone(resolved_at)

    def test_drain_accepted_queue_scoped_to_queue_ids_leaves_unrelated_accepted_rows_pending(self) -> None:
        target_source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        target_queue_id = self._insert_queue_row(
            source_record_id=target_source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        unrelated_source_record_id = self._insert_source_record("qwen3-5-omni-plus-unrelated")
        unrelated_queue_id = self._insert_queue_row(
            source_record_id=unrelated_source_record_id,
            candidate_model_id=1,
            status="accepted",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus-unrelated"]},
        )

        summary = resolver.drain_accepted_queue(self.conn, queue_ids=[target_queue_id])

        self.assertEqual(summary["processed"], 1)
        self.assertEqual(summary["aliases_upserted"], 1)
        self.assertEqual(summary["records_updated"], 1)
        self.assertEqual(summary["skipped"], 0)
        self.assertEqual(self._queue_state(target_queue_id)[0], "accepted")
        self.assertIsNotNone(self._queue_state(target_queue_id)[1])
        self.assertEqual(self._queue_state(unrelated_queue_id), ("accepted", None))
        self.assertIsNotNone(self._linked_alias_id(target_source_record_id))
        self.assertIsNone(self._linked_alias_id(unrelated_source_record_id))
        aliases = self.conn.execute("SELECT alias_string FROM model_alias ORDER BY alias_string").fetchall()
        self.assertEqual([row[0] for row in aliases], ["alibaba-qwen3-5-omni-plus"])

    def _insert_source_record(self, source_model_id: str) -> int:
        snapshot_id = 100 + self.conn.execute("SELECT COUNT(*) FROM source_snapshot").fetchone()[0]
        self.conn.execute(
            """
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES (?, 'artificialanalysis', 'memory://artificialanalysis', '2026-01-02T00:00:00Z', ?, 'test', NULL)
            """,
            (snapshot_id, f"hash-{snapshot_id}"),
        )
        cursor = self.conn.execute(
            """
            INSERT INTO source_model_record
                (source_snapshot_id, source_model_id, display_name, provider_name, raw_record_json, parsed_fields_json)
            VALUES (?, ?, 'Qwen3.5 Omni Plus', 'Alibaba', '{}', '{}')
            """,
            (snapshot_id, source_model_id),
        )
        return int(cursor.lastrowid)

    def _insert_queue_row(
        self,
        *,
        source_record_id: int,
        candidate_model_id: int | None,
        status: str,
        features: dict[str, object],
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (source_record_id, candidate_model_id, reason, features_json, status, created_at)
            VALUES (?, ?, 'manual acceptance test fixture', ?, ?, '2026-01-02T00:00:00Z')
            """,
            (source_record_id, candidate_model_id, json.dumps(features), status),
        )
        return int(cursor.lastrowid)

    def _alias_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM model_alias").fetchone()[0])

    def _linked_alias_id(self, source_record_id: int) -> int | None:
        return self.conn.execute(
            "SELECT model_alias_id FROM source_model_record WHERE id = ?",
            (source_record_id,),
        ).fetchone()[0]

    def _queue_state(self, queue_id: int) -> tuple[str, str | None]:
        return self.conn.execute(
            "SELECT status, resolved_at FROM entity_resolution_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()

    def _table_exists(self, table_name: str) -> bool:
        return (
            self.conn.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
                """,
                (table_name,),
            ).fetchone()
            is not None
        )

    def _audit_count(self) -> int:
        if not self._table_exists("entity_resolution_audit"):
            return 0
        return int(self.conn.execute("SELECT COUNT(*) FROM entity_resolution_audit").fetchone()[0])


class _ExistingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
