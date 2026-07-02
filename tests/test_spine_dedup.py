from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import spine


class SpineDedupCollisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        self.conn.executescript(schema_path.read_text())
        self.conn.execute(
            """
            INSERT INTO source (id, name, ingestion_class, auth_type)
            VALUES ('dedup_test', 'Dedup test source', 'D', 'none')
            """
        )

    def test_find_alias_collisions_reports_shared_alias_across_models(self) -> None:
        self.conn.executemany(
            """
            INSERT INTO model (id, canonical_slug, created_at, updated_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            [
                (1, "openai/gpt-4.1"),
                (2, "anthropic/claude-sonnet-4"),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO model_alias (
                source_id,
                alias_string,
                alias_normalized,
                alias_kind,
                model_id,
                resolution_method,
                confidence,
                first_seen_at,
                last_seen_at
            )
            VALUES (
                'dedup_test', ?, 'shared-model', 'display_name', ?,
                'manual_override', 1.0, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """,
            [
                ("Shared Model", 1),
                ("shared-model", 2),
            ],
        )

        collisions = spine.find_alias_collisions(self.conn)

        self.assertEqual(len(collisions), 1)
        collision = collisions[0]
        self.assertEqual(collision["alias_normalized"], "shared-model")
        self.assertEqual(set(collision["model_ids"]), {1, 2})
        self.assertEqual(
            set(collision["canonical_slugs"]),
            {"openai/gpt-4.1", "anthropic/claude-sonnet-4"},
        )

    def test_first_party_provider_gate_excludes_known_reexporters(self) -> None:
        first_party_cases = ["openai", "anthropic", "google"]
        reexporter_cases = ["nvidia", "inceptron"]

        for provider_id in first_party_cases:
            with self.subTest(provider_id=provider_id):
                self.assertTrue(spine.is_first_party_provider(provider_id))

        for provider_id in reexporter_cases:
            with self.subTest(provider_id=provider_id):
                self.assertFalse(spine.is_first_party_provider(provider_id))

    def test_models_dev_reexport_provider_attaches_alias_without_minting_canonical(self) -> None:
        self.conn.execute(
            """
            INSERT INTO source (id, name, ingestion_class, auth_type)
            VALUES ('models_dev', 'models.dev', 'A', 'none')
            """
        )
        self.conn.execute(
            """
            INSERT INTO source_snapshot (
                id,
                source_id,
                url,
                fetched_at,
                content_hash,
                parser_version
            )
            VALUES (
                1,
                'models_dev',
                'https://models.dev/api.json',
                '2026-01-01T00:00:00Z',
                'dedup-reexport-collision-test',
                'test'
            )
            """
        )
        self.conn.executemany(
            """
            INSERT INTO source_model_record (
                source_snapshot_id,
                source_model_id,
                raw_record_json,
                parsed_fields_json
            )
            VALUES (1, ?, '{}', '{}')
            """,
            [
                ("openai/gpt-4.1",),
                ("nvidia/openai/gpt-4.1",),
            ],
        )

        spine.build_spine(self.conn)

        canonical_rows = self.conn.execute(
            "SELECT id, canonical_slug FROM model ORDER BY canonical_slug"
        ).fetchall()
        self.assertEqual(canonical_rows, [(1, "openai/gpt-4.1")])
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM model WHERE canonical_slug LIKE 'nvidia/%'"
            ).fetchone()[0],
            0,
        )
        reexport_alias = self.conn.execute(
            """
            SELECT alias_kind, model_id
            FROM model_alias
            WHERE source_id = 'models_dev'
              AND alias_string = 'nvidia/openai/gpt-4.1'
            """
        ).fetchone()
        self.assertEqual(reexport_alias, ("reexport_id", canonical_rows[0][0]))


if __name__ == "__main__":
    unittest.main()
