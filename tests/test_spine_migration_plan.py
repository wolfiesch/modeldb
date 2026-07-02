from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import spine


class SpineReexportMigrationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        self.conn.executescript(schema_path.read_text())
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
                'spine-migration-plan-test',
                'test'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO benchmark (id, name, category, metric_default)
            VALUES ('migration_eval', 'Migration eval', 'reasoning', 'accuracy')
            """
        )

    def _insert_model(self, model_id: int, canonical_slug: str) -> None:
        self.conn.execute(
            """
            INSERT INTO model (id, canonical_slug, created_at, updated_at)
            VALUES (?, ?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            (model_id, canonical_slug),
        )

    def _insert_alias(
        self,
        alias_id: int,
        alias_string: str,
        alias_normalized: str,
        model_id: int,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO model_alias (
                id,
                source_id,
                alias_string,
                alias_normalized,
                alias_kind,
                model_id,
                resolution_method,
                confidence,
                source_snapshot_id,
                first_seen_at,
                last_seen_at
            )
            VALUES (
                ?, 'models_dev', ?, ?, 'api_model_id', ?,
                'manual_override', 1.0, 1,
                '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z'
            )
            """,
            (alias_id, alias_string, alias_normalized, model_id),
        )

    def _seed_reexport_duplicate_with_all_fk_surfaces(self) -> None:
        self._insert_model(1, "deepseek/deepseek-v4-flash")
        self._insert_model(2, "nvidia/deepseek-ai/deepseek-v4-flash")
        self._insert_alias(
            1,
            "deepseek-ai/DeepSeek-V4-Flash",
            "deepseek-ai-deepseek-v4-flash",
            1,
        )
        self._insert_alias(
            2,
            "nvidia/deepseek-ai/deepseek-v4-flash",
            "deepseek-ai-deepseek-v4-flash",
            2,
        )
        self.conn.execute(
            """
            INSERT INTO alias_history (
                id,
                alias_id,
                model_id,
                observed_from,
                evidence_snapshot_id,
                confidence
            )
            VALUES (1, 2, 2, '2026-01-01T00:00:00Z', 1, 1.0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO entity_resolution_queue (
                id,
                candidate_model_id,
                reason,
                features_json,
                status,
                created_at
            )
            VALUES (1, 2, 'alias collision', '{"alias":"deepseek-ai-deepseek-v4-flash"}', 'pending', '2026-01-01T00:00:00Z')
            """
        )
        self.conn.execute(
            """
            INSERT INTO provider_surface (
                id,
                provider_id,
                surface_type,
                endpoint_model_id,
                model_id,
                source_snapshot_id,
                metadata_json
            )
            VALUES (
                1,
                'nvidia',
                'reexport',
                'nvidia/deepseek-ai/deepseek-v4-flash',
                2,
                1,
                '{}'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO model_artifact (
                id,
                model_id,
                source_id,
                artifact_ref,
                artifact_type,
                author,
                metadata_json
            )
            VALUES (
                1,
                2,
                'models_dev',
                'nvidia/deepseek-ai/deepseek-v4-flash',
                'weights_url',
                'nvidia',
                '{}'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO model_capability (
                model_id,
                capability,
                value,
                source_snapshot_id,
                confidence
            )
            VALUES (1, 'context_window', '128000', 1, 1.0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO model_capability (
                model_id,
                capability,
                value,
                source_snapshot_id,
                confidence
            )
            VALUES (2, 'context_window', '128000', 1, 1.0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO price_component (
                id,
                model_id,
                provider_surface_id,
                source_id,
                component,
                unit,
                amount,
                source_snapshot_id
            )
            VALUES (1, 2, 1, 'models_dev', 'input_token', '1m_tokens', 0.25, 1)
            """
        )
        self.conn.execute(
            """
            INSERT INTO benchmark_result (
                id,
                model_id,
                provider_surface_id,
                benchmark_id,
                score,
                metric,
                measured_at,
                source_snapshot_id,
                raw_record_json
            )
            VALUES (1, 2, 1, 'migration_eval', 0.75, 'accuracy', '2026-01-01T00:00:00Z', 1, '{}')
            """
        )

    def _row_counts(self) -> dict[str, int]:
        tables = (
            "model",
            "model_alias",
            "alias_history",
            "entity_resolution_queue",
            "provider_surface",
            "model_artifact",
            "model_capability",
            "price_component",
            "benchmark_result",
        )
        return {
            table: self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }

    def _direct_model_fk_values(self) -> dict[str, list[tuple[object, ...]]]:
        return {
            "model_alias.model_id": self.conn.execute(
                "SELECT id, model_id FROM model_alias ORDER BY id"
            ).fetchall(),
            "alias_history.model_id": self.conn.execute(
                "SELECT id, model_id FROM alias_history ORDER BY id"
            ).fetchall(),
            "entity_resolution_queue.candidate_model_id": self.conn.execute(
                """
                SELECT id, candidate_model_id
                FROM entity_resolution_queue
                ORDER BY id
                """
            ).fetchall(),
            "provider_surface.model_id": self.conn.execute(
                "SELECT id, model_id FROM provider_surface ORDER BY id"
            ).fetchall(),
            "model_artifact.model_id": self.conn.execute(
                "SELECT id, model_id FROM model_artifact ORDER BY id"
            ).fetchall(),
            "model_capability.model_id": self.conn.execute(
                """
                SELECT model_id, capability, source_snapshot_id, value
                FROM model_capability
                ORDER BY model_id, capability, source_snapshot_id
                """
            ).fetchall(),
            "price_component.model_id": self.conn.execute(
                "SELECT id, model_id FROM price_component ORDER BY id"
            ).fetchall(),
            "benchmark_result.model_id": self.conn.execute(
                "SELECT id, model_id FROM benchmark_result ORDER BY id"
            ).fetchall(),
        }

    def test_reexport_merge_plan_reports_all_fk_counts_capability_conflicts_and_is_read_only(
        self,
    ) -> None:
        self._seed_reexport_duplicate_with_all_fk_surfaces()
        before_counts = self._row_counts()
        before_fk_values = self._direct_model_fk_values()

        plans = spine.plan_reexport_model_merges(self.conn)

        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan["duplicate_model_id"], 2)
        self.assertEqual(plan["duplicate_slug"], "nvidia/deepseek-ai/deepseek-v4-flash")
        self.assertEqual(plan["target_model_id"], 1)
        self.assertEqual(plan["target_slug"], "deepseek/deepseek-v4-flash")
        self.assertEqual(plan["reexport_provider"], "nvidia")
        self.assertEqual(
            plan["fk_counts"],
            {
                "model_alias.model_id": 1,
                "alias_history.model_id": 1,
                "entity_resolution_queue.candidate_model_id": 1,
                "provider_surface.model_id": 1,
                "model_artifact.model_id": 1,
                "model_capability.model_id": 1,
                "price_component.model_id": 1,
                "benchmark_result.model_id": 1,
            },
        )
        capability_conflicts = [
            {
                "duplicate_model_id": conflict.get("duplicate_model_id"),
                "target_model_id": conflict.get("target_model_id"),
                "capability": conflict.get("capability"),
                "source_snapshot_id": conflict.get("source_snapshot_id"),
                "duplicate_value": conflict.get("duplicate_value"),
                "target_value": conflict.get("target_value"),
            }
            for conflict in plan["capability_conflicts"]
        ]
        self.assertIn(
            {
                "duplicate_model_id": 2,
                "target_model_id": 1,
                "capability": "context_window",
                "source_snapshot_id": 1,
                "duplicate_value": "128000",
                "target_value": "128000",
            },
            capability_conflicts,
        )
        self.assertEqual(self._row_counts(), before_counts)
        self.assertEqual(self._direct_model_fk_values(), before_fk_values)

    def test_reexport_merge_plan_ignores_alias_collision_without_reexport_provider(self) -> None:
        self._insert_model(1, "deepseek/deepseek-v4-flash")
        self._insert_model(2, "openai/deepseek-v4-flash")
        self._insert_alias(
            1,
            "deepseek-ai/DeepSeek-V4-Flash",
            "deepseek-ai-deepseek-v4-flash",
            1,
        )
        self._insert_alias(
            2,
            "openai/deepseek-v4-flash",
            "deepseek-ai-deepseek-v4-flash",
            2,
        )

        self.assertEqual(spine.plan_reexport_model_merges(self.conn), [])


if __name__ == "__main__":
    unittest.main()
