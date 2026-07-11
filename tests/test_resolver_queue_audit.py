from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


class ResolverQueueAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
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
            VALUES
                (1, 'alibaba/qwen3.5-omni-plus', 'alibaba', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (2, 'anthropic/claude-opus-4', 'anthropic', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00');
            """
        )

    def test_accept_creates_audit_table_and_records_prior_queue_state(self) -> None:
        source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        queue_id = self._insert_queue_row(
            source_record_id=source_record_id,
            candidate_model_id=None,
            status="pending",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        self.assertFalse(self._table_exists("entity_resolution_audit"))

        resolver.accept_queue_row(self.conn, queue_id=queue_id, candidate_model_id=1)

        self.assertTrue(self._table_exists("entity_resolution_audit"))
        self.assertEqual(
            self.conn.execute(
                "SELECT candidate_model_id, status, resolved_at FROM entity_resolution_queue WHERE id = ?",
                (queue_id,),
            ).fetchone(),
            (1, "accepted", None),
        )
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "accept")
        self.assertEqual(rows[0]["queue_id"], queue_id)
        self.assertEqual(rows[0]["source_record_id"], source_record_id)
        self.assertEqual(rows[0]["candidate_model_id"], 1)
        details = json.loads(rows[0]["details_json"])
        self.assertEqual(details["prior_status"], "pending")
        self.assertIsNone(details["prior_candidate_model_id"])

    def test_drain_creates_audit_table_and_records_alias_materialization(self) -> None:
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
        self.assertFalse(self._table_exists("entity_resolution_audit"))

        resolver.drain_accepted_queue(self.conn)

        self.assertTrue(self._table_exists("entity_resolution_audit"))
        rows = self._audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["action"], "drain")
        self.assertEqual(rows[0]["queue_id"], queue_id)
        self.assertEqual(rows[0]["source_record_id"], source_record_id)
        self.assertEqual(rows[0]["candidate_model_id"], 1)
        alias_ids = [
            row[0]
            for row in self.conn.execute(
                "SELECT id FROM model_alias WHERE model_id = 1 ORDER BY id"
            ).fetchall()
        ]
        self.assertEqual(len(alias_ids), 2)
        self._assert_details_describe_materialized_aliases(
            json.loads(rows[0]["details_json"]), alias_ids
        )

    def test_audit_rows_are_append_only_across_repeated_accept_and_drain_workflows(self) -> None:
        first_source_record_id = self._insert_source_record("qwen3-5-omni-plus")
        first_queue_id = self._insert_queue_row(
            source_record_id=first_source_record_id,
            candidate_model_id=None,
            status="pending",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )

        resolver.accept_queue_row(self.conn, queue_id=first_queue_id, candidate_model_id=1)
        resolver.drain_accepted_queue(self.conn)
        first_audit_rows = self._audit_row_snapshots()
        self.assertEqual([row[1] for row in first_audit_rows], ["accept", "drain"])

        second_source_record_id = self._insert_source_record("claude-opus-4")
        second_queue_id = self._insert_queue_row(
            source_record_id=second_source_record_id,
            candidate_model_id=None,
            status="pending",
            features={"provider_scoped_candidates": ["anthropic-claude-opus-4"]},
        )
        resolver.accept_queue_row(self.conn, queue_id=second_queue_id, candidate_model_id=2)
        resolver.drain_accepted_queue(self.conn)

        all_audit_rows = self._audit_row_snapshots()
        self.assertEqual(all_audit_rows[: len(first_audit_rows)], first_audit_rows)
        self.assertEqual(
            [(row[1], row[2]) for row in all_audit_rows],
            [
                ("accept", first_queue_id),
                ("drain", first_queue_id),
                ("accept", second_queue_id),
                ("drain", second_queue_id),
            ],
        )

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
            VALUES (?, ?, ?, ?, '{}', '{}')
            """,
            (snapshot_id, source_model_id, source_model_id, "Fixture Provider"),
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
            VALUES (?, ?, 'manual audit test fixture', ?, ?, '2026-01-02T00:00:00Z')
            """,
            (source_record_id, candidate_model_id, json.dumps(features, sort_keys=True), status),
        )
        return int(cursor.lastrowid)

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

    def _audit_rows(self) -> list[sqlite3.Row]:
        old_factory = self.conn.row_factory
        self.conn.row_factory = sqlite3.Row
        try:
            return self.conn.execute(
                """
                SELECT action, queue_id, source_record_id, candidate_model_id, details_json
                FROM entity_resolution_audit
                ORDER BY rowid
                """
            ).fetchall()
        finally:
            self.conn.row_factory = old_factory

    def _audit_row_snapshots(self) -> list[tuple[object, ...]]:
        return self.conn.execute(
            """
            SELECT rowid, action, queue_id, source_record_id, candidate_model_id, details_json
            FROM entity_resolution_audit
            ORDER BY rowid
            """
        ).fetchall()

    def _assert_details_describe_materialized_aliases(
        self, details: dict[str, object], alias_ids: list[int]
    ) -> None:
        ids = (
            details.get("alias_ids")
            or details.get("created_alias_ids")
            or details.get("upserted_alias_ids")
        )
        if ids is not None:
            self.assertEqual(ids, alias_ids)
            return

        count = details.get("alias_count", details.get("aliases_upserted"))
        if count is not None:
            self.assertEqual(count, len(alias_ids))
            return

        self.fail("drain audit details must include materialized alias ids or alias count")


if __name__ == "__main__":
    unittest.main()
