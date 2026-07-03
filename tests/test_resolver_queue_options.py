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


class QueueCandidateOptionsTests(unittest.TestCase):
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
                confidence REAL NOT NULL DEFAULT 1.0,
                source_snapshot_id INTEGER,
                first_seen_at TEXT,
                last_seen_at TEXT
            );
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
                (1, 'qwen/qwen3.5-122b-a10b', 'qwen', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (2, 'alibaba/qwen3.5-122b-a10b', 'alibaba', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (3, 'alibaba/qwen3.5-14b', 'alibaba', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00');
            INSERT INTO model_alias
                (source_id, alias_string, alias_normalized, alias_kind, model_id,
                 resolution_method, confidence, first_seen_at, last_seen_at)
            VALUES
                ('models_dev', 'qwen3.5-122b-a10b', 'qwen3-5-122b-a10b', 'api_model_id', 1,
                 'fixture', 1.0, '2026-07-02T19:00:00+00:00', '2026-07-02T21:00:00+00:00'),
                ('models_dev', 'alibaba/qwen3.5-122b-a10b', 'alibaba-qwen3-5-122b-a10b', 'api_model_id', 2,
                 'fixture', 0.8, '2026-07-02T19:00:00+00:00', '2026-07-02T20:00:00+00:00');
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES
                (1, 'artificialanalysis', 'memory://artificialanalysis', '2026-07-02T19:00:00+00:00', 'hash-1', 'test', NULL);
            """
        )
        self._insert_pending_alibaba_qwen_row()

    def test_pending_provider_scoped_candidates_rank_matching_provider_model_and_leave_queue_row_unchanged(self) -> None:
        before = self._queue_resolution_state(201)

        payload = resolver.queue_candidate_options(self.conn, 201, limit=5)

        self.assertEqual(self._queue_resolution_state(201), before)
        self.assertEqual(payload["queue_id"], 201)
        self.assertEqual(payload["source_record_id"], 101)
        self.assertEqual(payload["source_id"], "artificialanalysis")
        self.assertEqual(payload["status"], "pending")
        self.assertIsNone(payload["candidate_model_id"])
        self.assertIsNone(payload["resolved_at"])
        self.assertEqual(payload["provider"], "alibaba")
        self.assertEqual(payload["source_model_id"], "qwen3-5-122b-a10b-non-reasoning")

        options = payload["options"]
        self.assertGreaterEqual(len(options), 1)
        self.assertEqual(
            {key: options[0][key] for key in ("model_id", "canonical_slug", "developer_id")},
            {
                "model_id": 2,
                "canonical_slug": "alibaba/qwen3.5-122b-a10b",
                "developer_id": "alibaba",
            },
        )
        first_reason = self._option_display_reason(options[0])
        self.assertIn("alibaba-qwen3-5-122b-a10b", first_reason)
        self.assertIn("alibaba/qwen3.5-122b-a10b", first_reason)

        ranked_model_ids = [option["model_id"] for option in options]
        if 1 in ranked_model_ids:
            self.assertLess(ranked_model_ids.index(2), ranked_model_ids.index(1))

    def test_options_cli_prints_json_payload_without_accepting_or_resolving_the_row(self) -> None:
        before = self._queue_resolution_state(201)
        stdout = io.StringIO()

        with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
            with redirect_stdout(stdout):
                exit_code = resolver.main(["options", "201"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(self._queue_resolution_state(201), before)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["queue_id"], 201)
        self.assertEqual(payload["options"][0]["model_id"], 2)
        self.assertEqual(payload["options"][0]["canonical_slug"], "alibaba/qwen3.5-122b-a10b")

    def _insert_pending_alibaba_qwen_row(self) -> None:
        features = {
            "model_creator_slug": "alibaba",
            "slug": "qwen3-5-122b-a10b-non-reasoning",
            "model_name": "Qwen3.5 122B A10B Non-Reasoning",
            "provider_scoped_candidates": [
                "alibaba-qwen3-5-122b-a10b-non-reasoning",
                "alibaba-qwen3-5-122b-a10b",
            ],
        }
        self.conn.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json)
            VALUES (?, 1, ?, ?, 'Alibaba', ?, ?)
            """,
            (
                101,
                "qwen3-5-122b-a10b-non-reasoning",
                "Qwen3.5 122B A10B Non-Reasoning",
                json.dumps({"slug": features["slug"]}, sort_keys=True),
                json.dumps({"slug": features["slug"]}, sort_keys=True),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (id, source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (?, ?, NULL, 'pending AA options fixture', ?, 'pending', '2026-07-02T19:00:00+00:00', NULL)
            """,
            (201, 101, json.dumps(features, sort_keys=True)),
        )

    def _queue_resolution_state(self, queue_id: int) -> tuple[object, ...]:
        return self.conn.execute(
            """
            SELECT status, candidate_model_id, resolved_at
            FROM entity_resolution_queue
            WHERE id = ?
            """,
            (queue_id,),
        ).fetchone()

    def _option_display_reason(self, option: dict[str, object]) -> str:
        for key in ("reason", "match"):
            value = option.get(key)
            if isinstance(value, str) and value.strip():
                return value
        self.fail(f"option lacks a CLI display reason/match string: {option!r}")


class _ExistingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
