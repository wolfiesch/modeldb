from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


class QueueReviewExportTests(unittest.TestCase):
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
                (1, 'alibaba/qwen3.5-122b-a10b', 'alibaba', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (2, 'qwen/qwen3.5-122b-a10b', 'qwen', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00');
            INSERT INTO model_alias
                (source_id, alias_string, alias_normalized, alias_kind, model_id,
                 resolution_method, confidence, first_seen_at, last_seen_at)
            VALUES
                ('models_dev', 'alibaba/qwen3.5-122b-a10b', 'alibaba-qwen3-5-122b-a10b', 'api_model_id', 1,
                 'fixture', 1.0, '2026-07-02T19:00:00+00:00', '2026-07-02T20:00:00+00:00'),
                ('models_dev', 'qwen3.5-122b-a10b', 'qwen3-5-122b-a10b', 'api_model_id', 2,
                 'fixture', 1.0, '2026-07-02T19:00:00+00:00', '2026-07-02T20:00:00+00:00');
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES
                (1, 'artificialanalysis', 'memory://artificialanalysis', '2026-07-02T19:00:00+00:00', 'hash-aa', 'test', NULL),
                (2, 'openrouter', 'memory://openrouter', '2026-07-02T19:00:00+00:00', 'hash-or', 'test', NULL);
            """
        )

    def test_csv_export_includes_header_pending_aa_row_top_option_and_copyable_approval_json(self) -> None:
        self._insert_pending_aa_row_with_matching_option()

        csv_text = resolver.queue_review_export(self.conn, source_id="artificialanalysis", format="csv")
        rows, fieldnames = self._read_csv_export(csv_text)

        self.assertEqual(len(rows), 1)
        self.assertTrue(
            {
                "queue_id",
                "provider",
                "family",
                "model_name",
                "source_model_id",
                "top_model_id",
                "top_canonical_slug",
                "top_score",
                "top_match",
                "suggested_approval_json",
            }.issubset(set(fieldnames)),
            fieldnames,
        )
        [row] = rows
        self.assertEqual(row["queue_id"], "201")
        self.assertEqual(row["provider"], "alibaba")
        self.assertEqual(row["family"], "qwen3-5-122b-a10b")
        self.assertEqual(row["model_name"], "Qwen3.5 122B A10B Non-Reasoning")
        self.assertEqual(row["source_model_id"], "qwen3-5-122b-a10b-non-reasoning")
        self.assertEqual(row["top_model_id"], "1")
        self.assertEqual(row["top_canonical_slug"], "alibaba/qwen3.5-122b-a10b")
        self.assertEqual(row["top_score"], "110")
        self.assertIn("exact_provider_scoped_alias", row["top_match"])
        self.assertEqual(
            json.loads(row["suggested_approval_json"]),
            {"queue_id": 201, "candidate_model_id": 1},
        )

    def test_markdown_cli_export_prints_copyable_table_with_top_option_and_approval_json(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        stdout = io.StringIO()

        with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
            with redirect_stdout(stdout):
                exit_code = resolver.main(["queue-export", "--format", "markdown", "artificialanalysis"])

        markdown = stdout.getvalue()
        table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
        self.assertEqual(exit_code, 0)
        self.assertGreaterEqual(len(table_lines), 3)
        self.assertTrue(all(line.endswith("|") for line in table_lines), table_lines)
        self.assertIn("| queue_id |", table_lines[0])
        self.assertIn("| provider |", table_lines[0])
        self.assertIn("| suggested_approval_json |", table_lines[0])
        self.assertRegex(table_lines[1], r"^\|(?:\s*:?-+:?\s*\|)+$")
        data_row = "\n".join(table_lines[2:])
        for value in (
            "201",
            "alibaba",
            "qwen3-5-122b-a10b",
            "Qwen3.5 122B A10B Non-Reasoning",
            "qwen3-5-122b-a10b-non-reasoning",
            "1",
            "alibaba/qwen3.5-122b-a10b",
            "110",
            "exact_provider_scoped_alias",
        ):
            self.assertIn(value, data_row)
        self.assertRegex(data_row, r'"queue_id"\s*:\s*201')
        self.assertRegex(data_row, r'"candidate_model_id"\s*:\s*1')


    def test_csv_export_keeps_suggested_and_unsuggested_rows_by_default(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        self._insert_pending_aa_row_without_matching_options()

        csv_text = resolver.queue_review_export(self.conn, source_id="artificialanalysis", format="csv")
        rows, _ = self._read_csv_export(csv_text)

        self.assertEqual([row["queue_id"] for row in rows], ["201", "202"])
        self.assertEqual(
            json.loads(rows[0]["suggested_approval_json"]),
            {"queue_id": 201, "candidate_model_id": 1},
        )
        self.assertEqual(rows[1]["suggested_approval_json"], "")

    def test_csv_export_with_suggested_only_filters_blank_suggestions(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        self._insert_pending_aa_row_without_matching_options()

        csv_text = resolver.queue_review_export(
            self.conn,
            source_id="artificialanalysis",
            format="csv",
            suggested_only=True,
        )
        rows, _ = self._read_csv_export(csv_text)

        self.assertEqual([row["queue_id"] for row in rows], ["201"])
        self.assertEqual(
            json.loads(rows[0]["suggested_approval_json"]),
            {"queue_id": 201, "candidate_model_id": 1},
        )

    def test_queue_export_cli_suggested_only_prints_csv_for_suggested_rows(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        self._insert_pending_aa_row_without_matching_options()
        stdout = io.StringIO()

        with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
            with redirect_stdout(stdout):
                exit_code = resolver.main(["queue-export", "--suggested-only"])

        rows, fieldnames = self._read_csv_export(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertIn("suggested_approval_json", fieldnames)
        self.assertEqual([row["queue_id"] for row in rows], ["201"])
        self.assertEqual(
            json.loads(rows[0]["suggested_approval_json"]),
            {"queue_id": 201, "candidate_model_id": 1},
        )

    def test_markdown_export_with_suggested_only_filters_blank_suggestions(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        self._insert_pending_aa_row_without_matching_options()

        markdown = resolver.queue_review_export(
            self.conn,
            source_id="artificialanalysis",
            format="markdown",
            suggested_only=True,
        )

        table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
        self.assertEqual(len(table_lines), 3)
        self.assertIn("| suggested_approval_json |", table_lines[0])
        [data_row] = table_lines[2:]
        self.assertIn("| 201 |", data_row)
        self.assertIn("Qwen3.5 122B A10B Non-Reasoning", data_row)
        self.assertRegex(data_row, r'"candidate_model_id"\s*:\s*1')
        self.assertNotIn("202", data_row)
        self.assertNotIn("Mystery Model Preview", data_row)

    def test_csv_export_keeps_pending_rows_without_options_and_leaves_approval_blank(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        self._insert_pending_aa_row_without_matching_options()

        csv_text = resolver.queue_review_export(self.conn, source_id="artificialanalysis", format="csv")
        rows, _ = self._read_csv_export(csv_text)
        no_option_row = self._row_by_queue_id(rows, "202")

        self.assertEqual(no_option_row["provider"], "mistral")
        self.assertEqual(no_option_row["family"], "mystery-model")
        self.assertEqual(no_option_row["model_name"], "Mystery Model Preview")
        self.assertEqual(no_option_row["source_model_id"], "mystery-model-preview")
        self.assertIn(no_option_row["top_model_id"], ("", "null"))
        self.assertIn(no_option_row["top_canonical_slug"], ("", "null"))
        self.assertIn(no_option_row["top_score"], ("", "null"))
        self.assertIn(no_option_row["top_match"], ("", "null"))
        self.assertIn(no_option_row["suggested_approval_json"], ("", "null"))

    def test_export_is_read_only_and_does_not_accept_or_resolve_queue_rows(self) -> None:
        self._insert_pending_aa_row_with_matching_option()
        self._insert_pending_aa_row_without_matching_options()
        before = self._queue_resolution_state()

        resolver.queue_review_export(self.conn, source_id="artificialanalysis", format="csv")
        resolver.queue_review_export(self.conn, source_id="artificialanalysis", format="markdown")

        self.assertEqual(self._queue_resolution_state(), before)

    def _insert_pending_aa_row_with_matching_option(self) -> None:
        features = {
            "model_creator_slug": "alibaba",
            "slug": "qwen3-5-122b-a10b-non-reasoning",
            "model_name": "Qwen3.5 122B A10B Non-Reasoning",
            "provider_scoped_candidates": [
                "alibaba-qwen3-5-122b-a10b-non-reasoning",
                "alibaba-qwen3-5-122b-a10b",
            ],
        }
        self._insert_source_record(
            source_record_id=101,
            snapshot_id=1,
            source_model_id="qwen3-5-122b-a10b-non-reasoning",
            display_name="Qwen3.5 122B A10B Non-Reasoning",
            provider_name="Alibaba",
            parsed_fields={"slug": "qwen3-5-122b-a10b-non-reasoning"},
        )
        self._insert_queue_row(201, source_record_id=101, features=features)

    def _insert_pending_aa_row_without_matching_options(self) -> None:
        features = {
            "model_creator_slug": "mistral",
            "slug": "mystery-model-preview",
            "model_name": "Mystery Model Preview",
            "provider_scoped_candidates": ["mistral-mystery-model-preview"],
        }
        self._insert_source_record(
            source_record_id=102,
            snapshot_id=1,
            source_model_id="mystery-model-preview",
            display_name="Mystery Model Preview",
            provider_name="Mistral",
            parsed_fields={"slug": "mystery-model-preview"},
        )
        self._insert_queue_row(202, source_record_id=102, features=features)

    def _insert_source_record(
        self,
        *,
        source_record_id: int,
        snapshot_id: int,
        source_model_id: str,
        display_name: str,
        provider_name: str,
        parsed_fields: dict[str, object],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_record_id,
                snapshot_id,
                source_model_id,
                display_name,
                provider_name,
                json.dumps({"slug": parsed_fields.get("slug")}, sort_keys=True),
                json.dumps(parsed_fields, sort_keys=True),
            ),
        )

    def _insert_queue_row(self, queue_id: int, *, source_record_id: int, features: dict[str, object]) -> None:
        self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (id, source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (?, ?, NULL, 'pending AA export fixture', ?, 'pending', '2026-07-02T19:00:00+00:00', NULL)
            """,
            (queue_id, source_record_id, json.dumps(features, sort_keys=True)),
        )

    def _read_csv_export(self, csv_text: str) -> tuple[list[dict[str, str]], list[str]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        return list(reader), list(reader.fieldnames or [])

    def _row_by_queue_id(self, rows: list[dict[str, str]], queue_id: str) -> dict[str, str]:
        for row in rows:
            if row["queue_id"] == queue_id:
                return row
        self.fail(f"missing queue row {queue_id!r} in export: {rows!r}")

    def _queue_resolution_state(self) -> list[tuple[object, ...]]:
        return self.conn.execute(
            """
            SELECT id, status, candidate_model_id, resolved_at
            FROM entity_resolution_queue
            ORDER BY id
            """
        ).fetchall()


class _ExistingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
