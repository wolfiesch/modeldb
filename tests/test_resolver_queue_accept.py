from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


class AcceptQueueRowTests(unittest.TestCase):
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
                (1, 'anthropic/claude-4-sonnet', 'anthropic', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (2, 'alibaba/qwen3.5-omni-plus', 'alibaba', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00');
            """
        )

    def test_accepts_pending_unresolved_row_with_explicit_candidate_without_resolving(self) -> None:
        queue_id = self._insert_queue_row(
            candidate_model_id=None,
            status="pending",
            features={
                "model_creator_slug": "alibaba",
                "provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"],
            },
        )
        original_features_json = self._features_json(queue_id)

        resolver.accept_queue_row(self.conn, queue_id=queue_id, candidate_model_id=2)

        candidate_model_id, status, resolved_at = self.conn.execute(
            """
            SELECT candidate_model_id, status, resolved_at
            FROM entity_resolution_queue
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()
        self.assertEqual(candidate_model_id, 2)
        self.assertEqual(status, "accepted")
        self.assertIsNone(resolved_at)
        self.assertEqual(self._features_json(queue_id), original_features_json)
        self.assertFalse(self._table_exists("model_alias"))

    def test_unknown_candidate_model_refuses_acceptance_and_leaves_row_unchanged(self) -> None:
        queue_id = self._insert_queue_row(
            candidate_model_id=None,
            status="pending",
            features={"provider_scoped_candidates": ["missing-model"]},
        )
        before = self._queue_row(queue_id)

        with self.assertRaises(ValueError):
            resolver.accept_queue_row(self.conn, queue_id=queue_id, candidate_model_id=999)

        self.assertEqual(self._queue_row(queue_id), before)
        self.assertFalse(self._table_exists("model_alias"))

    def test_pending_row_with_existing_candidate_refuses_acceptance_and_leaves_row_unchanged(self) -> None:
        queue_id = self._insert_queue_row(
            candidate_model_id=1,
            status="pending",
            features={"provider_scoped_candidates": ["anthropic-claude-4-sonnet"]},
        )
        before = self._queue_row(queue_id)

        with self.assertRaises(ValueError):
            resolver.accept_queue_row(self.conn, queue_id=queue_id, candidate_model_id=2)

        self.assertEqual(self._queue_row(queue_id), before)
        self.assertFalse(self._table_exists("model_alias"))

    def test_already_resolved_row_refuses_acceptance_and_leaves_row_unchanged(self) -> None:
        queue_id = self._insert_queue_row(
            candidate_model_id=1,
            status="accepted",
            features={"provider_scoped_candidates": ["anthropic-claude-4-sonnet"]},
            resolved_at="2026-07-02T20:00:00+00:00",
        )
        before = self._queue_row(queue_id)

        with self.assertRaises(ValueError):
            resolver.accept_queue_row(self.conn, queue_id=queue_id, candidate_model_id=2)

        self.assertEqual(self._queue_row(queue_id), before)
        self.assertFalse(self._table_exists("model_alias"))

    def test_refuses_pending_row_when_same_source_record_already_resolved(self) -> None:
        self._insert_queue_row(
            candidate_model_id=1,
            status="accepted",
            features={"provider_scoped_candidates": ["anthropic-claude-4-sonnet"]},
            resolved_at="2026-07-02T20:00:00+00:00",
        )
        queue_id = self._insert_queue_row(
            candidate_model_id=None,
            status="pending",
            features={"provider_scoped_candidates": ["alibaba-qwen3-5-omni-plus"]},
        )
        before = self._queue_row(queue_id)

        with self.assertRaises(ValueError):
            resolver.accept_queue_row(self.conn, queue_id=queue_id, candidate_model_id=2)

        self.assertEqual(self._queue_row(queue_id), before)
        self.assertFalse(self._table_exists("model_alias"))

    def _insert_queue_row(
        self,
        *,
        candidate_model_id: int | None,
        status: str,
        features: dict[str, object],
        resolved_at: str | None = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (101, ?, 'manual accept fixture', ?, ?, '2026-07-02T19:00:00+00:00', ?)
            """,
            (candidate_model_id, json.dumps(features, sort_keys=True), status, resolved_at),
        )
        return int(cursor.lastrowid)

    def _queue_row(self, queue_id: int) -> tuple[object, ...]:
        return self.conn.execute(
            """
            SELECT id, source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at
            FROM entity_resolution_queue
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()

    def _features_json(self, queue_id: int) -> str:
        return self.conn.execute(
            "SELECT features_json FROM entity_resolution_queue WHERE id = ?",
            (queue_id,),
        ).fetchone()[0]

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        return row is not None


if __name__ == "__main__":
    unittest.main()
