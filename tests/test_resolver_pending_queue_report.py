from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


class PendingQueueReportTests(unittest.TestCase):
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
            """
        )

    def test_groups_pending_null_candidate_rows_by_provider_and_family_suffixes(self) -> None:
        suffixes = [
            "non-reasoning",
            "reasoning",
            "preview",
            "high",
            "low",
            "medium",
            "xhigh",
        ]
        self._insert_snapshot(1, "artificialanalysis")
        for index, suffix in enumerate(suffixes, start=1):
            slug = f"qwen3-5-122b-a10b-{suffix}"
            source_record_id = 100 + index
            self._insert_source_record(
                source_record_id,
                snapshot_id=1,
                source_model_id=slug,
                display_name=f"Qwen3.5 122B A10B {suffix}",
                provider_name="Alibaba",
                parsed_fields={"slug": slug},
            )
            self._insert_queue_row(
                200 + index,
                source_record_id=source_record_id,
                candidate_model_id=None,
                status="pending",
                features={
                    "model_creator_slug": "alibaba",
                    "provider_scoped_candidates": [f"alibaba-{slug}"],
                },
            )

        report = resolver.pending_queue_report(self.conn, source_id="artificialanalysis")
        groups = report["groups"]

        self.assertEqual(report["total"], len(suffixes))
        self.assertEqual(len(groups), 1)
        [group] = groups
        self.assertEqual(group["provider"], "alibaba")
        self.assertEqual(group["family"], "qwen3-5-122b-a10b")
        self.assertEqual(group["count"], len(suffixes))

    def test_filters_to_pending_artificial_analysis_rows_and_returns_cli_samples_without_mutating(self) -> None:
        self._insert_snapshot(1, "artificialanalysis")
        self._insert_snapshot(2, "openrouter")
        self._insert_source_record(
            101,
            snapshot_id=1,
            source_model_id="qwen3-5-122b-a10b-non-reasoning",
            display_name="Qwen3.5 122B A10B Non-Reasoning",
            provider_name="Alibaba",
            parsed_fields={"slug": "qwen3-5-122b-a10b-non-reasoning"},
        )
        self._insert_queue_row(
            201,
            source_record_id=101,
            candidate_model_id=None,
            status="pending",
            features={
                "model_creator_slug": "alibaba",
                "slug": "qwen3-5-122b-a10b-non-reasoning",
                "model_name": "Qwen3.5 122B A10B Non-Reasoning",
                "provider_scoped_candidates": [
                    "alibaba-qwen3-5-122b-a10b-non-reasoning",
                    "alibaba-qwen3-5-122b-a10b",
                ],
            },
        )
        self._insert_source_record(
            102,
            snapshot_id=1,
            source_model_id="qwen3-5-122b-a10b-preview-medium",
            display_name="Qwen3.5 122B A10B Preview Medium",
            provider_name="Alibaba",
            parsed_fields={"slug": "qwen3-5-122b-a10b-preview-medium"},
        )
        self._insert_queue_row(
            202,
            source_record_id=102,
            candidate_model_id=None,
            status="pending",
            features={
                "model_creator_slug": "alibaba",
                "slug": "qwen3-5-122b-a10b-preview-medium",
                "model_name": "Qwen3.5 122B A10B Preview Medium",
                "provider_scoped_candidates": ["alibaba-qwen3-5-122b-a10b-preview-medium"],
            },
        )
        self._insert_source_record(
            103,
            snapshot_id=2,
            source_model_id="qwen3-5-122b-a10b-non-reasoning",
            display_name="OpenRouter Qwen",
            provider_name="OpenRouter",
            parsed_fields={"slug": "qwen3-5-122b-a10b-non-reasoning"},
        )
        self._insert_queue_row(
            203,
            source_record_id=103,
            candidate_model_id=None,
            status="pending",
            features={
                "model_creator_slug": "alibaba",
                "slug": "qwen3-5-122b-a10b-non-reasoning",
                "model_name": "OpenRouter Qwen",
                "provider_scoped_candidates": ["alibaba-qwen3-5-122b-a10b-non-reasoning"],
            },
        )
        self._insert_source_record(
            104,
            snapshot_id=1,
            source_model_id="claude-4-sonnet-preview",
            display_name="Claude 4 Sonnet Preview",
            provider_name="Anthropic",
            parsed_fields={"slug": "claude-4-sonnet-preview"},
        )
        self._insert_queue_row(
            204,
            source_record_id=104,
            candidate_model_id=None,
            status="accepted",
            features={
                "model_creator_slug": "anthropic",
                "slug": "claude-4-sonnet-preview",
                "model_name": "Claude 4 Sonnet Preview",
                "provider_scoped_candidates": ["anthropic-claude-4-sonnet-preview"],
            },
            resolved_at="2026-07-02T20:00:00+00:00",
        )
        self._insert_source_record(
            105,
            snapshot_id=1,
            source_model_id="gpt-5-high",
            display_name="GPT-5 High",
            provider_name="OpenAI",
            parsed_fields={"slug": "gpt-5-high"},
        )
        self._insert_queue_row(
            205,
            source_record_id=105,
            candidate_model_id=None,
            status="pending",
            features={
                "model_creator_slug": "openai",
                "slug": "gpt-5-high",
                "model_name": "GPT-5 High",
                "provider_scoped_candidates": ["openai-gpt-5-high"],
            },
            resolved_at="2026-07-02T20:05:00+00:00",
        )
        self._insert_source_record(
            106,
            snapshot_id=1,
            source_model_id="qwen3-5-122b-a10b",
            display_name="Qwen3.5 122B A10B",
            provider_name="Alibaba",
            parsed_fields={"slug": "qwen3-5-122b-a10b"},
        )
        self._insert_queue_row(
            206,
            source_record_id=106,
            candidate_model_id=99,
            status="pending",
            features={
                "model_creator_slug": "alibaba",
                "slug": "qwen3-5-122b-a10b",
                "model_name": "Qwen3.5 122B A10B",
                "provider_scoped_candidates": ["alibaba-qwen3-5-122b-a10b"],
            },
        )
        before_rows = self._queue_rows()

        report = resolver.pending_queue_report(self.conn, source_id="artificialanalysis")

        self.assertEqual(self._queue_rows(), before_rows)
        self.assertEqual(report["source_id"], "artificialanalysis")
        self.assertEqual(report["total"], 2)
        groups = report["groups"]
        self.assertEqual(len(groups), 1)
        [group] = groups
        self.assertEqual(group["provider"], "alibaba")
        self.assertEqual(group["family"], "qwen3-5-122b-a10b")
        self.assertEqual(group["count"], 2)
        self.assertEqual(
            group["samples"],
            [
                {
                    "queue_id": 201,
                    "source_record_id": 101,
                    "source_model_id": "qwen3-5-122b-a10b-non-reasoning",
                    "model_name": "Qwen3.5 122B A10B Non-Reasoning",
                    "slug": "qwen3-5-122b-a10b-non-reasoning",
                    "first_candidate": "alibaba-qwen3-5-122b-a10b-non-reasoning",
                    "candidate_count": 2,
                },
                {
                    "queue_id": 202,
                    "source_record_id": 102,
                    "source_model_id": "qwen3-5-122b-a10b-preview-medium",
                    "model_name": "Qwen3.5 122B A10B Preview Medium",
                    "slug": "qwen3-5-122b-a10b-preview-medium",
                    "first_candidate": "alibaba-qwen3-5-122b-a10b-preview-medium",
                    "candidate_count": 1,
                },
            ],
        )

    def _insert_snapshot(self, snapshot_id: int, source_id: str) -> None:
        self.conn.execute(
            """
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES (?, ?, ?, '2026-07-02T19:00:00+00:00', ?, 'test', NULL)
            """,
            (snapshot_id, source_id, f"memory://{source_id}", f"hash-{snapshot_id}"),
        )

    def _insert_source_record(
        self,
        source_record_id: int,
        *,
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
                json.dumps({"slug": parsed_fields.get("slug")}),
                json.dumps(parsed_fields),
            ),
        )

    def _insert_queue_row(
        self,
        queue_id: int,
        *,
        source_record_id: int,
        candidate_model_id: int | None,
        status: str,
        features: dict[str, object],
        resolved_at: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (id, source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (?, ?, ?, 'pending AA report fixture', ?, ?, '2026-07-02T19:00:00+00:00', ?)
            """,
            (queue_id, source_record_id, candidate_model_id, json.dumps(features), status, resolved_at),
        )

    def _queue_rows(self) -> list[tuple[object, ...]]:
        return self.conn.execute(
            """
            SELECT id, source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at
            FROM entity_resolution_queue
            ORDER BY id
            """
        ).fetchall()


if __name__ == "__main__":
    unittest.main()
