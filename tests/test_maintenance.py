from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from store.maintenance import main, run_maintenance

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"



class MaintenanceDedupFactsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "models.sqlite"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.executescript(
                """
                INSERT INTO source (id, name) VALUES ('epoch', 'Epoch AI');
                INSERT INTO source_snapshot (id, source_id, url, fetched_at, content_hash, parser_version)
                  VALUES (1, 'epoch', 'https://epoch.ai/', '2026-08-01T00:00:00+00:00', 'h1', '0.1.0');
                INSERT INTO model (id, canonical_slug, created_at, updated_at)
                  VALUES (1, 'openai/gpt-5', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
                INSERT INTO benchmark (id, name) VALUES ('gpqa_diamond', 'GPQA Diamond');
                """
            )

    def _insert_result(self, *, score: float, eval_condition: str = '{"model_version":"gpt-5"}',
                       benchmark_id: str = "gpqa_diamond", model_id: int | None = 1) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            cur = conn.execute(
                """INSERT INTO benchmark_result
                     (model_id, benchmark_id, score, eval_condition_json, source_snapshot_id)
                   VALUES (?, ?, ?, ?, 1)""",
                (model_id, benchmark_id, score, eval_condition),
            )
            return int(cur.lastrowid or 0)

    def _insert_price(self, *, component: str, valid_from: str, valid_to: str | None) -> int:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            cur = conn.execute(
                """INSERT INTO price_component
                     (model_id, provider_surface_id, source_id, component, unit, currency,
                      amount, valid_from, valid_to, source_snapshot_id)
                   VALUES (1, NULL, 'models_dev', ?, '1m_tokens', 'USD', 3.0, ?, ?, 1)""",
                (component, valid_from, valid_to),
            )
            return int(cur.lastrowid or 0)

    def _fetch_results(self) -> list[tuple]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT id, model_id, benchmark_id, score FROM benchmark_result ORDER BY id"
            ).fetchall()

    def _fetch_prices(self) -> list[tuple]:
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(
                "SELECT id, component, valid_from, valid_to FROM price_component ORDER BY id"
            ).fetchall()

    # -- benchmark_result dedup ------------------------------------------------

    def test_removes_exact_duplicates_and_keeps_first_seen_row(self) -> None:
        first = self._insert_result(score=0.71)
        second = self._insert_result(score=0.71)
        self._insert_result(score=0.72)  # same benchmark, different score: distinct fact

        result = run_maintenance(self.db_path)

        self.assertEqual(result["benchmark_duplicates_removed"], 1)
        self.assertEqual(
            self._fetch_results(),
            [(first, 1, "gpqa_diamond", 0.71), (second + 1, 1, "gpqa_diamond", 0.72)],
        )

    def test_dedup_treats_null_eval_condition_as_equal_key(self) -> None:
        self._insert_result(score=0.5, eval_condition="")
        self._insert_result(score=0.5, eval_condition="")

        result = run_maintenance(self.db_path)

        self.assertEqual(result["benchmark_duplicates_removed"], 1)
        self.assertEqual(len(self._fetch_results()), 1)

    def test_dedup_separates_rows_from_different_snapshots(self) -> None:
        first = self._insert_result(score=0.71)
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """INSERT INTO source_snapshot (id, source_id, url, fetched_at, content_hash, parser_version)
                   VALUES (2, 'epoch', 'https://epoch.ai/', '2026-09-01T00:00:00+00:00', 'h2', '0.1.0')"""
            )
            conn.execute(
                """INSERT INTO benchmark_result
                     (model_id, benchmark_id, score, eval_condition_json, source_snapshot_id)
                   VALUES (1, 'gpqa_diamond', 0.71, '{"model_version":"gpt-5"}', 2)"""
            )

        run_maintenance(self.db_path)

        rows = [row[0] for row in self._fetch_results()]
        self.assertEqual(rows, [first, first + 1])

    def test_dedup_is_noop_on_clean_database(self) -> None:
        self._insert_result(score=0.71)

        first = run_maintenance(self.db_path)
        second = run_maintenance(self.db_path)

        self.assertEqual(first["benchmark_duplicates_removed"], 0)
        self.assertEqual(second["benchmark_duplicates_removed"], 0)
        self.assertEqual(len(self._fetch_results()), 1)

    # -- price window capping --------------------------------------------------

    def test_caps_open_ended_window_at_newer_observation(self) -> None:
        older = self._insert_price(component="input_token", valid_from="2026-08-01T00:00:00+00:00", valid_to=None)
        newer = self._insert_price(component="input_token", valid_from="2026-09-01T00:00:00+00:00", valid_to=None)

        result = run_maintenance(self.db_path)

        self.assertEqual(result["price_windows_capped"], 1)
        self.assertEqual(
            self._fetch_prices(),
            [
                (older, "input_token", "2026-08-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
                (newer, "input_token", "2026-09-01T00:00:00+00:00", None),
            ],
        )

    def test_caps_window_that_extends_past_newer_observation(self) -> None:
        self._insert_price(component="input_token", valid_from="2026-08-01T00:00:00+00:00",
                           valid_to="2026-12-31T00:00:00+00:00")
        self._insert_price(component="input_token", valid_from="2026-09-01T00:00:00+00:00", valid_to=None)

        result = run_maintenance(self.db_path)

        self.assertEqual(result["price_windows_capped"], 1)
        older_row = self._fetch_prices()[0]
        self.assertEqual(older_row[3], "2026-09-01T00:00:00+00:00")

    def test_does_not_cap_adjacent_or_distinct_component_windows(self) -> None:
        self._insert_price(component="input_token", valid_from="2026-08-01T00:00:00+00:00",
                           valid_to="2026-08-31T00:00:00+00:00")
        self._insert_price(component="input_token", valid_from="2026-09-01T00:00:00+00:00", valid_to=None)
        self._insert_price(component="output_token", valid_from="2026-07-01T00:00:00+00:00", valid_to=None)

        result = run_maintenance(self.db_path)

        self.assertEqual(result["price_windows_capped"], 0)
        self.assertEqual(self._fetch_prices()[2][3], None)

    def test_price_capping_is_idempotent(self) -> None:
        self._insert_price(component="input_token", valid_from="2026-08-01T00:00:00+00:00", valid_to=None)
        self._insert_price(component="input_token", valid_from="2026-09-01T00:00:00+00:00", valid_to=None)

        first = run_maintenance(self.db_path)
        second = run_maintenance(self.db_path)

        self.assertEqual(first["price_windows_capped"], 1)
        self.assertEqual(second["price_windows_capped"], 0)

    # -- CLI --------------------------------------------------------------------

    def test_cli_prints_summary_and_exits_zero(self) -> None:
        self._insert_result(score=0.71)
        self._insert_result(score=0.71)
        self._insert_price(component="input_token", valid_from="2026-08-01T00:00:00+00:00", valid_to=None)
        self._insert_price(component="input_token", valid_from="2026-09-01T00:00:00+00:00", valid_to=None)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(["--db", str(self.db_path), "--dedup-facts"])

        self.assertEqual(exit_code, 0)
        self.assertIn("removed 1 duplicate benchmark_result row(s)", stdout.getvalue())
        self.assertIn("capped 1 overlapping price window(s)", stdout.getvalue())
        self.assertIn(str(self.db_path), stdout.getvalue())

    def test_cli_requires_an_explicit_task(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--db", str(self.db_path)])
        self.assertEqual(ctx.exception.code, 2)

    def test_maintenance_leaves_other_tables_untouched(self) -> None:
        self._insert_result(score=0.71)
        self._insert_result(score=0.71)
        with closing(sqlite3.connect(self.db_path)) as conn:
            before = conn.execute(
                "SELECT (SELECT COUNT(*) FROM model), (SELECT COUNT(*) FROM benchmark), "
                "(SELECT COUNT(*) FROM source_snapshot), (SELECT COUNT(*) FROM source)"
            ).fetchone()

        run_maintenance(self.db_path)

        with closing(sqlite3.connect(self.db_path)) as conn:
            after = conn.execute(
                "SELECT (SELECT COUNT(*) FROM model), (SELECT COUNT(*) FROM benchmark), "
                "(SELECT COUNT(*) FROM source_snapshot), (SELECT COUNT(*) FROM source)"
            ).fetchone()
        self.assertEqual(before, after)
    def test_relink_connects_unlinked_row_to_model(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO model_alias (model_id, alias_string, alias_normalized, alias_kind, confidence, source_id, first_seen_at, last_seen_at) "
                "VALUES (1, 'gpt-5', 'gpt-5', 'bare_name', 1.0, 'epoch', '2026-08-01', '2026-08-01')"
            )
        r_id = self._insert_result(score=0.88, model_id=None, eval_condition='{"model_version":"gpt-5"}')
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertIsNone(conn.execute("SELECT model_id FROM benchmark_result WHERE id = ?", (r_id,)).fetchone()[0])

        result = run_maintenance(self.db_path, dedup=False, relink=True)
        self.assertEqual(result["benchmarks_relinked"], 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT model_id FROM benchmark_result WHERE id = ?", (r_id,)).fetchone()[0], 1)

        # Idempotent second run
        result2 = run_maintenance(self.db_path, dedup=False, relink=True)
        self.assertEqual(result2["benchmarks_relinked"], 0)

    def test_cli_relink_benchmarks_and_all_flags(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO model_alias (model_id, alias_string, alias_normalized, alias_kind, confidence, source_id, first_seen_at, last_seen_at) "
                "VALUES (1, 'gpt-5', 'gpt-5', 'bare_name', 1.0, 'epoch', '2026-08-01', '2026-08-01')"
            )
        self._insert_result(score=0.88, model_id=None, eval_condition='{"model_version":"gpt-5"}')
        self._insert_result(score=0.71)
        self._insert_result(score=0.71)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = main(["--db", str(self.db_path), "--all"])
        self.assertEqual(code, 0)
        self.assertIn("removed 1 duplicate benchmark_result row(s)", stdout.getvalue())
        self.assertIn("relinked 1 benchmark_result row(s)", stdout.getvalue())

if __name__ == "__main__":
    unittest.main()
