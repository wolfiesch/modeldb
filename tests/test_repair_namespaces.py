from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import repair_namespaces, spine

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


class NamespaceRepairTestCase(unittest.TestCase):
    """Shared fixture: schema + models_dev source + one snapshot."""

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(SCHEMA_PATH.read_text())
        self.conn.execute(
            "INSERT INTO source (id, name, ingestion_class, auth_type)"
            " VALUES ('models_dev', 'models.dev', 'A', 'none')"
        )
        self.conn.execute(
            """
            INSERT INTO source_snapshot (id, source_id, url, fetched_at, content_hash, parser_version)
            VALUES (1, 'models_dev', 'https://models.dev/api.json',
                    '2026-08-01T00:00:00Z', 'repair-test', 'test')
            """
        )
        self.conn.commit()

    def _insert_model(self, slug: str, *, developer_id: str | None = None,
                      release_date: str | None = None,
                      canonical_confidence: str = "verified") -> int:
        if developer_id:
            self.conn.execute(
                "INSERT OR IGNORE INTO organization (id, display_name) VALUES (?,?)",
                (developer_id, developer_id),
            )
        cur = self.conn.execute(
            """
            INSERT INTO model (canonical_slug, developer_id, release_date,
                               canonical_confidence, created_at, updated_at)
            VALUES (?,?,?,?, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            (slug, developer_id, release_date, canonical_confidence),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid

    def _insert_alias(self, alias_string: str, model_id: int,
                      kind: str = "api_model_id") -> int:
        from resolve.normalize import normalize_alias

        cur = self.conn.execute(
            """
            INSERT INTO model_alias (source_id, alias_string, alias_normalized,
                                     alias_kind, model_id, resolution_method,
                                     confidence, first_seen_at, last_seen_at)
            VALUES ('models_dev', ?, ?, ?, ?, 'exact_provider_doc', 1.0,
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')
            """,
            (alias_string, normalize_alias(alias_string), kind, model_id),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid
    def _seed_shell_with_full_fk_surface(self, slug: str,
                                         release_date: str | None) -> int:
        """Shell row carrying one row in every model-referencing table."""
        shell_id = self._insert_model(slug, developer_id=slug.split("/")[0],
                                      release_date=release_date)
        alias_id = self._insert_alias(slug, shell_id)
        self._insert_alias(slug.split("/", 1)[1], shell_id, kind="bare_name")
        self.conn.execute(
            "INSERT INTO alias_history (alias_id, model_id, observed_from, confidence)"
            " VALUES (?,?, '2026-01-01T00:00:00Z', 1.0)",
            (alias_id, shell_id),
        )
        self.conn.execute(
            "INSERT INTO benchmark (id, name) VALUES ('gpqa_diamond', 'GPQA Diamond')"
        )
        self.conn.execute(
            "INSERT INTO benchmark_result (model_id, benchmark_id, score, source_snapshot_id)"
            " VALUES (?, 'gpqa_diamond', 41.5, 1)",
            (shell_id,),
        )
        self.conn.execute(
            "INSERT INTO model_capability (model_id, capability, value, source_snapshot_id, confidence)"
            " VALUES (?, 'context_window', '131072', 1, 1.0)",
            (shell_id,),
        )
        self.conn.execute(
            "INSERT INTO provider_surface (provider_id, surface_type, region,"
            " endpoint_model_id, model_id, source_snapshot_id)"
            " VALUES ('nvidia', 'api', NULL, ?, ?, 1)",
            (slug, shell_id),
        )
        self.conn.execute(
            "INSERT INTO model_artifact (model_id, source_id, artifact_ref, artifact_type)"
            " VALUES (?, 'models_dev', ?, 'hf_repo')",
            (shell_id, slug),
        )
        self.conn.execute(
            "INSERT INTO price_component (model_id, component, unit, amount)"
            " VALUES (?, 'input_token', '1m_tokens', 0.6)",
            (shell_id,),
        )
        self.conn.execute(
            "INSERT INTO source_model_record (source_snapshot_id, source_model_id,"
            " raw_record_json, model_alias_id) VALUES (1, ?, '{}', ?)",
            (slug, alias_id),
        )
        self.conn.execute(
            "INSERT INTO entity_resolution_queue (source_record_id, reason, features_json,"
            " status, created_at) VALUES (1, 'test', '{}', 'pending', '2026-01-01T00:00:00Z')"
        )
        self.conn.execute(
            "UPDATE entity_resolution_queue SET candidate_model_id = ? WHERE id = 1",
            (shell_id,),
        )
        self.conn.execute(
            "INSERT INTO entity_resolution_audit (queue_id, candidate_model_id,"
            " action, details_json, created_at)"
            " VALUES (1, ?, 'drain', '{}', '2026-01-01T00:00:00Z')",
            (shell_id,),
        )
        self.conn.commit()
        return shell_id

    def _multi_slash_count(self) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM model WHERE canonical_slug LIKE '%/%/%'"
        ).fetchone()[0]

    def _apply(self) -> dict:
        return repair_namespaces.apply_namespace_repairs(
            self.conn, allow_test_memory_backup=True
        )


class RepairNamespaceCollapsesTests(NamespaceRepairTestCase):
    def test_host_prefixed_shell_creates_creator_canonical_and_repoints_all_fks(self) -> None:
        shell_id = self._seed_shell_with_full_fk_surface(
            "nvidia/meta/llama-3.1-70b-instruct", release_date="2024-07-23"
        )

        summary = self._apply()

        self.assertEqual(summary["applied"], 1)
        self.assertEqual(summary["created"], 1)
        self.assertEqual(self._multi_slash_count(), 0)

        target = self.conn.execute(
            "SELECT id, developer_id, release_date FROM model"
            " WHERE canonical_slug = 'meta/llama-3.1-70b-instruct'"
        ).fetchone()
        self.assertIsNotNone(target)
        target_id = int(target[0])
        self.assertEqual(target[1], "meta")
        self.assertEqual(target[2], "2024-07-23")  # release date preserved

        for table, column in repair_namespaces.MODEL_FK_REFERENCES:
            with self.subTest(fk=f"{table}.{column}"):
                self.assertEqual(
                    self.conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",
                        (shell_id,),
                    ).fetchone()[0],
                    0,
                    "shell must retain no references",
                )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM benchmark_result WHERE model_id = ?",
                (target_id,),
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM model_capability WHERE model_id = ?",
                (target_id,),
            ).fetchone()[0],
            1,
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT id FROM model WHERE id = ?", (shell_id,)
            ).fetchone()
        )

    def test_host_facing_slug_survives_as_alias_of_canonical(self) -> None:
        shell_id = self._seed_shell_with_full_fk_surface(
            "nvidia/meta/llama-3.1-70b-instruct", release_date="2024-07-23"
        )
        self._apply()

        target_id = self.conn.execute(
            "SELECT id FROM model WHERE canonical_slug = 'meta/llama-3.1-70b-instruct'"
        ).fetchone()[0]
        for kind in ("api_model_id", "reexport_id"):
            with self.subTest(alias_kind=kind):
                row = self.conn.execute(
                    "SELECT model_id FROM model_alias"
                    " WHERE alias_string = 'nvidia/meta/llama-3.1-70b-instruct'"
                    "   AND alias_kind = ?",
                    (kind,),
                ).fetchone()
                if row is not None:
                    self.assertEqual(int(row[0]), int(target_id))
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT id FROM model_alias"
                " WHERE alias_string = 'nvidia/meta/llama-3.1-70b-instruct'"
                "   AND alias_kind = 'reexport_id'"
            ).fetchone(),
            "explicit reexport_id alias must exist even if api_model_id were absent",
        )

    def test_self_prefixed_host_path_mints_host_canonical(self) -> None:
        self._seed_shell_with_full_fk_surface(
            "poolside/poolside/laguna-m.1", release_date="2026-04-28"
        )

        summary = self._apply()

        self.assertEqual(summary["applied"], 1)
        self.assertEqual(self._multi_slash_count(), 0)
        row = self.conn.execute(
            "SELECT developer_id, release_date FROM model"
            " WHERE canonical_slug = 'poolside/laguna-m.1'"
        ).fetchone()
        self.assertEqual(row[0], "poolside")
        self.assertEqual(row[1], "2026-04-28")

    def test_thinkingmachines_self_prefix_repair(self) -> None:
        self._insert_model(
            "thinkingmachines/thinkingmachines/Inkling-Small",
            developer_id="thinkingmachines",
            release_date="2026-07-30",
        )

        self._apply()

        self.assertEqual(self._multi_slash_count(), 0)
        self.assertIsNotNone(
            self.conn.execute(
                "SELECT id FROM model WHERE canonical_slug = 'thinkingmachines/Inkling-Small'"
            ).fetchone()
        )


class RepairNamespaceMergeTests(NamespaceRepairTestCase):
    def _seed_duplicate_merge_case(self) -> tuple[int, int]:
        """inceptron shell + existing minimax canonical, both with facts."""
        shell_id = self._seed_shell_with_full_fk_surface(
            "inceptron/MiniMaxAI/MiniMax-M2.5", release_date="2026-05-12"
        )
        target_id = self._insert_model(
            "minimax/MiniMax-M2.5", developer_id="minimax", release_date="2026-05-12"
        )
        self._insert_alias("minimax/MiniMax-M2.5", target_id)
        self._insert_alias("MiniMax-M2.5", target_id, kind="bare_name")
        self.conn.execute(
            "INSERT INTO benchmark (id, name) VALUES ('mmlu_pro', 'MMLU Pro')"
        )
        self.conn.execute(
            "INSERT INTO benchmark_result (model_id, benchmark_id, score, source_snapshot_id)"
            " VALUES (?, 'mmlu_pro', 72.0, 1)",
            (target_id,),
        )
        self.conn.commit()
        return shell_id, target_id

    def test_merge_into_existing_canonical_keeps_both_fact_sets(self) -> None:
        shell_id, target_id = self._seed_duplicate_merge_case()

        summary = self._apply()

        self.assertEqual(summary["applied"], 1)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(summary["created"], 0)
        self.assertEqual(self._multi_slash_count(), 0)

        scores = sorted(
            row[0]
            for row in self.conn.execute(
                "SELECT score FROM benchmark_result WHERE model_id = ?", (target_id,)
            )
        )
        self.assertEqual(scores, [41.5, 72.0])  # shell fact + target fact coexist

        host_alias = self.conn.execute(
            "SELECT model_id FROM model_alias"
            " WHERE alias_string = 'inceptron/MiniMaxAI/MiniMax-M2.5'"
            "   AND alias_kind = 'api_model_id'"
        ).fetchone()
        self.assertEqual(int(host_alias[0]), int(target_id))

        self.assertIsNone(
            self.conn.execute("SELECT id FROM model WHERE id = ?", (shell_id,)).fetchone()
        )

    def test_differing_capability_conflict_skips_model_conservatively(self) -> None:
        shell_id, target_id = self._seed_duplicate_merge_case()
        self.conn.execute(
            "INSERT INTO model_capability (model_id, capability, value, source_snapshot_id, confidence)"
            " VALUES (?, 'context_window', '200000', 1, 1.0)",
            (target_id,),
        )
        self.conn.commit()

        summary = self._apply()

        self.assertEqual(summary["applied"], 0)
        self.assertEqual(summary["skipped_count"], 1)
        self.assertIn("capability conflict", summary["skipped_plans"][0]["reason"])
        self.assertEqual(self._multi_slash_count(), 1)  # shell untouched
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM model_capability WHERE model_id = ?", (shell_id,)
            ).fetchone()[0],
            "131072",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT value FROM model_capability WHERE model_id = ?", (target_id,)
            ).fetchone()[0],
            "200000",
        )


class RepairNamespaceSafetyTests(NamespaceRepairTestCase):
    def test_dry_run_plans_without_writing(self) -> None:
        self._seed_shell_with_full_fk_surface(
            "nvidia/meta/llama-3.1-70b-instruct", release_date="2024-07-23"
        )
        before = self.conn.execute(
            "SELECT canonical_slug FROM model ORDER BY canonical_slug"
        ).fetchall()

        plans = repair_namespaces.plan_namespace_repairs(self.conn)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["action"], "create")
        self.assertEqual(plans[0]["clean_slug"], "meta/llama-3.1-70b-instruct")
        self.assertEqual(
            self.conn.execute(
                "SELECT canonical_slug FROM model ORDER BY canonical_slug"
            ).fetchall(),
            before,
        )

    def test_repair_is_idempotent(self) -> None:
        self._seed_shell_with_full_fk_surface(
            "nvidia/meta/llama-3.1-70b-instruct", release_date="2024-07-23"
        )
        first = self._apply()
        second = self._apply()

        self.assertEqual(first["applied"], 1)
        self.assertEqual(second["planned"], 0)
        self.assertEqual(second["applied"], 0)
        self.assertEqual(self._multi_slash_count(), 0)

    def test_apply_requires_backup_path(self) -> None:
        self._seed_shell_with_full_fk_surface(
            "nvidia/meta/llama-3.1-70b-instruct", release_date="2024-07-23"
        )
        with self.assertRaises(RuntimeError):
            repair_namespaces.apply_namespace_repairs(self.conn)

    def test_cli_dry_run_prints_plan_and_leaves_db_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "fixture.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript(SCHEMA_PATH.read_text())
            conn.execute(
                "INSERT INTO source (id, name, ingestion_class, auth_type)"
                " VALUES ('models_dev', 'models.dev', 'A', 'none')"
            )
            conn.execute(
                "INSERT INTO organization (id, display_name) VALUES ('nvidia', 'NVIDIA')"
            )
            conn.execute(
                "INSERT INTO model (canonical_slug, developer_id, created_at, updated_at)"
                " VALUES ('nvidia/meta/llama-3.1-70b-instruct', 'nvidia',"
                " '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
            )
            conn.commit()
            conn.close()

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = repair_namespaces.main(["--dry-run", "--db", str(db_path)])

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("nvidia/meta/llama-3.1-70b-instruct", output)
            self.assertIn("->  meta/llama-3.1-70b-instruct", output)
            self.assertIn("[create", output)

            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM model WHERE canonical_slug LIKE '%/%/%'"
                    ).fetchone()[0],
                    1,
                )
            finally:
                conn.close()


class MintPathGuardTests(NamespaceRepairTestCase):
    """New ingestion must mint creator-canonical slugs, never multi-slash."""

    def _snapshot_rows(self, *source_model_ids: str) -> None:
        self.conn.executemany(
            """
            INSERT INTO source_model_record (
                source_snapshot_id, source_model_id, raw_record_json, parsed_fields_json
            ) VALUES (1, ?, '{}', '{}')
            """,
            [(source_model_id,) for source_model_id in source_model_ids],
        )

    def test_nested_first_party_ids_mint_creator_canonical_plus_host_alias(self) -> None:
        self._snapshot_rows(
            "meta/llama-3.1-70b-instruct",
            "poolside/poolside/laguna-m.1",
            "thinkingmachines/thinkingmachines/Inkling-Small",
        )

        spine.build_spine(self.conn)

        slugs = {
            row[0]
            for row in self.conn.execute("SELECT canonical_slug FROM model")
        }
        self.assertEqual(
            slugs,
            {
                "meta/llama-3.1-70b-instruct",
                "poolside/laguna-m.1",
                "thinkingmachines/Inkling-Small",
            },
        )
        for host_string in (
            "poolside/poolside/laguna-m.1",
            "thinkingmachines/thinkingmachines/Inkling-Small",
        ):
            with self.subTest(host_string=host_string):
                self.assertIsNotNone(
                    self.conn.execute(
                        "SELECT id FROM model_alias WHERE alias_string = ?",
                        (host_string,),
                    ).fetchone(),
                    "host-facing string must survive as an alias",
                )

    def test_unknown_nested_creator_routed_to_alias_path_not_minted(self) -> None:
        self._snapshot_rows(
            "poolside/acme/widget-x",
        )

        spine.build_spine(self.conn)

        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM model").fetchone()[0], 0
        )

    def test_build_spine_output_never_contains_multi_slash_canonical(self) -> None:
        self._snapshot_rows(
            "meta/llama-3.1-70b-instruct",
            "poolside/poolside/laguna-m.1",
            "thinkingmachines/thinkingmachines/Inkling-Small",
            "poolside/acme/widget-x",
            "nvidia/openai/gpt-4.1",  # re-export host stays gated
        )

        spine.build_spine(self.conn)

        self.assertEqual(self._multi_slash_count(), 0)


if __name__ == "__main__":
    unittest.main()
