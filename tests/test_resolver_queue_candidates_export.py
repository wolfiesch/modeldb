from __future__ import annotations

import csv
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


class QueueCandidatesExportTests(unittest.TestCase):
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
                (1, 'anthropic/claude-4-sonnet', 'anthropic', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'),
                (2, 'openai/gpt-5', 'openai', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00');
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES
                (1, 'artificialanalysis', 'memory://artificialanalysis', '2026-07-02T19:00:00+00:00', 'hash-aa', 'test', NULL),
                (2, 'openrouter', 'memory://openrouter', '2026-07-02T19:00:00+00:00', 'hash-or', 'test', NULL);
            """
        )

    def test_csv_export_includes_raw_pending_candidates_and_existing_model_ids(self) -> None:
        self._insert_queue_fixture(
            queue_id=201,
            source_record_id=101,
            source_model_id="claude-4-sonnet-preview",
            display_name="Claude 4 Sonnet Preview",
            provider_name="Anthropic",
            provider="anthropic",
            slug="claude-4-sonnet-preview",
            model_name="Claude 4 Sonnet Preview",
            provider_scoped_candidates=[
                "anthropic-claude-4-sonnet",
                "anthropic-claude-4-sonnet-preview",
            ],
        )
        self._insert_queue_fixture(
            queue_id=202,
            source_record_id=102,
            source_model_id="mystery-large",
            display_name="Mystery Large",
            provider_name="Mistral",
            provider="mistral",
            slug="mystery-large",
            model_name="Mystery Large",
            provider_scoped_candidates=["mistral-mystery-large"],
        )
        self._insert_queue_fixture(
            queue_id=203,
            source_record_id=103,
            source_model_id="gpt-5-high",
            display_name="GPT-5 High",
            provider_name="OpenAI",
            provider="openai",
            slug="gpt-5-high",
            model_name="GPT-5 High",
            provider_scoped_candidates=["openai-gpt-5"],
            status="accepted",
            candidate_model_id=2,
        )

        csv_text = resolver.queue_candidates_export(self.conn, source_id="artificialanalysis", format="csv")
        rows, fieldnames = self._read_csv_export(csv_text)

        self.assertEqual(
            fieldnames,
            [
                "queue_id",
                "provider",
                "family",
                "source_model_id",
                "model_name",
                "slug",
                "candidate_count",
                "provider_scoped_candidates",
                "existing_candidate_model_ids",
            ],
        )
        self.assertEqual([row["queue_id"] for row in rows], ["201", "202"])

        matched_row = self._row_by_queue_id(rows, "201")
        self.assertEqual(matched_row["provider"], "anthropic")
        self.assertEqual(matched_row["family"], "claude-4-sonnet")
        self.assertEqual(matched_row["source_model_id"], "claude-4-sonnet-preview")
        self.assertEqual(matched_row["model_name"], "Claude 4 Sonnet Preview")
        self.assertEqual(matched_row["slug"], "claude-4-sonnet-preview")
        self.assertEqual(matched_row["candidate_count"], "2")
        self.assertEqual(
            matched_row["provider_scoped_candidates"],
            "anthropic-claude-4-sonnet; anthropic-claude-4-sonnet-preview",
        )
        self.assertEqual(matched_row["existing_candidate_model_ids"], "1")

        unmatched_row = self._row_by_queue_id(rows, "202")
        self.assertEqual(unmatched_row["provider"], "mistral")
        self.assertEqual(unmatched_row["family"], "mystery-large")
        self.assertEqual(unmatched_row["candidate_count"], "1")
        self.assertEqual(unmatched_row["provider_scoped_candidates"], "mistral-mystery-large")
        self.assertEqual(unmatched_row["existing_candidate_model_ids"], "")

    def test_markdown_export_escapes_pipes_and_newlines_while_showing_raw_candidates(self) -> None:
        self._insert_queue_fixture(
            queue_id=301,
            source_record_id=301,
            source_model_id="claude-sonnet-weird",
            display_name="Claude | Sonnet\nPreview",
            provider_name="Anthropic",
            provider="anthropic",
            slug="claude|sonnet\npreview",
            model_name="Claude | Sonnet\nPreview",
            provider_scoped_candidates=[
                "anthropic-claude|sonnet\npreview",
                "anthropic-claude-4-sonnet",
            ],
        )

        markdown = resolver.queue_candidates_export(self.conn, source_id="artificialanalysis", format="markdown")
        table_lines = [line for line in markdown.splitlines() if line.startswith("|")]

        self.assertEqual(len(table_lines), 3)
        self.assertIn("| provider_scoped_candidates |", table_lines[0])
        self.assertRegex(table_lines[1], r"^\|(?:\s*:?-+:?\s*\|)+$")
        [data_row] = table_lines[2:]
        self.assertTrue(data_row.endswith("|"), data_row)
        self.assertIn("Claude \\| Sonnet Preview", data_row)
        self.assertIn("claude\\|sonnet", data_row)
        self.assertIn("anthropic-claude\\|sonnet", data_row)
        self.assertIn("preview", data_row)
        self.assertIn("anthropic-claude-4-sonnet", data_row)
        self.assertNotIn("suggested_approval_json", markdown)

    def test_cli_queue_candidates_export_prints_csv_without_mutating_queue_state(self) -> None:
        self._insert_queue_fixture(
            queue_id=401,
            source_record_id=401,
            source_model_id="claude-4-sonnet-preview",
            display_name="Claude 4 Sonnet Preview",
            provider_name="Anthropic",
            provider="anthropic",
            slug="claude-4-sonnet-preview",
            model_name="Claude 4 Sonnet Preview",
            provider_scoped_candidates=["anthropic-claude-4-sonnet"],
        )
        before = self._queue_resolution_state()
        stdout = io.StringIO()

        with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
            with redirect_stdout(stdout):
                exit_code = resolver.main(["queue-candidates-export"])

        rows, fieldnames = self._read_csv_export(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(self._queue_resolution_state(), before)
        self.assertEqual([row["queue_id"] for row in rows], ["401"])
        self.assertIn("provider_scoped_candidates", fieldnames)
        self.assertIn("existing_candidate_model_ids", fieldnames)
        self.assertNotIn("suggested_approval_json", fieldnames)
        self.assertNotIn("candidate_model_id", fieldnames)
        self.assertEqual(rows[0]["provider_scoped_candidates"], "anthropic-claude-4-sonnet")
        self.assertEqual(rows[0]["existing_candidate_model_ids"], "1")

    def _insert_queue_fixture(
        self,
        *,
        queue_id: int,
        source_record_id: int,
        source_model_id: str,
        display_name: str,
        provider_name: str,
        provider: str,
        slug: str,
        model_name: str,
        provider_scoped_candidates: list[str],
        status: str = "pending",
        candidate_model_id: int | None = None,
    ) -> None:
        self._insert_source_record(
            source_record_id=source_record_id,
            snapshot_id=1,
            source_model_id=source_model_id,
            display_name=display_name,
            provider_name=provider_name,
            parsed_fields={"slug": slug, "model_name": model_name, "model_creator_slug": provider},
        )
        features = {
            "model_creator_slug": provider,
            "slug": slug,
            "model_name": model_name,
            "provider_scoped_candidates": provider_scoped_candidates,
        }
        self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (id, source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (?, ?, ?, 'raw candidate export fixture', ?, ?, '2026-07-02T19:00:00+00:00', NULL)
            """,
            (queue_id, source_record_id, candidate_model_id, json.dumps(features, sort_keys=True), status),
        )

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
