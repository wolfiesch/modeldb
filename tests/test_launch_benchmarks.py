from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import launch_benchmarks

FIXTURE_SET = {
    "set_id": "acme_widget_2_card",
    "source_id": "hf_model_card",
    "url": "https://example.invalid/acme/widget-2",
    "published_at": "2026-07-30",
    "columns": (
        {"label": "Widget 2", "model_slug": "acme/widget-2", "condition": {"effort": "high"}},
        {"label": "Widget 1", "model_slug": "acme/widget-1", "condition": {}},
        {"label": "Rival X", "model_slug": None},
    ),
    "table_notes": ("Fixture note.",),
    "row_condition": {"harness": "fixture-harness"},
    "rows": (
        ("fixture_bench", "Fixture Bench", "percent", (81.5, 70.0, 99.9), {"tools": False}),
        ("fixture_bench_2", "Fixture Bench 2", "score", (1200, None, 1300), {}),
    ),
}

FIXTURE_CATALOG = {
    "fixture_bench": ("Fixture Bench", "coding", "percent", 1, "https://example.invalid/fb"),
    "fixture_bench_2": ("Fixture Bench 2", "agentic", "score", 0, None),
}


class LaunchBenchmarkPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        self.conn.executescript(schema_path.read_text())
        self.conn.execute(
            "INSERT INTO source (id, name, ingestion_class, auth_type) VALUES "
            "('hf_model_card','HF model cards','B','none'),"
            "('provider_blog','provider blog','C','none')"
        )
        self.conn.execute(
            "INSERT INTO organization (id, display_name) VALUES ('acme','Acme')"
        )
        for slug in ("acme/widget-2", "acme/widget-1"):
            self.conn.execute(
                """INSERT INTO model
                     (canonical_slug, developer_id, display_name, created_at, updated_at)
                   VALUES (?,?,?,'2026-07-30T00:00:00Z','2026-07-30T00:00:00Z')""",
                (slug, "acme", slug),
            )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (
            mock.patch.object(launch_benchmarks, "LAUNCH_BENCHMARK_SETS", (FIXTURE_SET,)),
            mock.patch.object(launch_benchmarks, "BENCHMARK_CATALOG", FIXTURE_CATALOG),
            mock.patch.object(launch_benchmarks, "REPO_ROOT", Path(tmp.name)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _results(self) -> list[tuple]:
        return self.conn.execute(
            """SELECT m.canonical_slug, br.benchmark_id, br.score, br.metric,
                      br.self_reported, br.measured_at, br.eval_condition_json
               FROM benchmark_result br JOIN model m ON m.id = br.model_id
               ORDER BY br.benchmark_id, m.canonical_slug"""
        ).fetchall()

    def test_writes_only_vendor_owned_columns_as_self_reported(self) -> None:
        summary = launch_benchmarks.promote_launch_benchmarks(self.conn)

        self.assertEqual(summary["results_inserted"], 3)
        # Rival X column (2 cells) plus Widget 1's blank cell on row 2.
        self.assertEqual(summary["comparison_or_blank_cells"], 3)
        self.assertEqual(summary["unresolved_models"], 0)

        rows = self._results()
        self.assertEqual(
            [(slug, bid, score) for slug, bid, score, *_ in rows],
            [("acme/widget-1", "fixture_bench", 70.0),
             ("acme/widget-2", "fixture_bench", 81.5),
             ("acme/widget-2", "fixture_bench_2", 1200.0)],
        )
        self.assertTrue(all(row[4] == 1 for row in rows))
        self.assertTrue(all(row[5] == "2026-07-30" for row in rows))

    def test_condition_merges_set_row_and_column_scopes(self) -> None:
        launch_benchmarks.promote_launch_benchmarks(self.conn)
        condition = json.loads(
            self.conn.execute(
                """SELECT br.eval_condition_json FROM benchmark_result br
                   JOIN model m ON m.id = br.model_id
                   WHERE m.canonical_slug='acme/widget-2' AND br.benchmark_id='fixture_bench'"""
            ).fetchone()[0]
        )
        self.assertEqual(
            condition, {"harness": "fixture-harness", "tools": False, "effort": "high"}
        )

    def test_raw_record_preserves_printed_labels_and_provenance(self) -> None:
        launch_benchmarks.promote_launch_benchmarks(self.conn)
        raw = json.loads(
            self.conn.execute(
                """SELECT br.raw_record_json FROM benchmark_result br
                   JOIN model m ON m.id = br.model_id
                   WHERE m.canonical_slug='acme/widget-1'"""
            ).fetchone()[0]
        )
        self.assertEqual(raw["printed_benchmark"], "Fixture Bench")
        self.assertEqual(raw["printed_column"], "Widget 1")
        self.assertEqual(raw["printed_value"], 70.0)
        self.assertEqual(raw["source_url"], FIXTURE_SET["url"])

    def test_catalog_preserves_higher_is_better_direction(self) -> None:
        launch_benchmarks.promote_launch_benchmarks(self.conn)
        rows = dict(
            self.conn.execute(
                "SELECT id, higher_is_better FROM benchmark ORDER BY id"
            ).fetchall()
        )
        self.assertEqual(rows, {"fixture_bench": 1, "fixture_bench_2": 0})

    def test_promote_is_idempotent(self) -> None:
        first = launch_benchmarks.promote_launch_benchmarks(self.conn)
        second = launch_benchmarks.promote_launch_benchmarks(self.conn)

        self.assertEqual(first["snapshots_created"], 1)
        self.assertEqual(second["snapshots_created"], 0)
        self.assertEqual(second["benchmarks_added"], 0)
        self.assertEqual(first["results_inserted"], second["results_inserted"])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM benchmark_result").fetchone()[0], 3
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM source_snapshot").fetchone()[0], 1
        )

    def test_row_width_mismatch_is_rejected(self) -> None:
        bad = {**FIXTURE_SET, "rows": (("fixture_bench", "Fixture Bench", "percent", (1.0,), {}),)}
        with mock.patch.object(launch_benchmarks, "LAUNCH_BENCHMARK_SETS", (bad,)):
            with self.assertRaises(ValueError):
                launch_benchmarks.promote_launch_benchmarks(self.conn)


class ShippedBenchmarkSetContentTests(unittest.TestCase):
    """The shipped sets are hand-transcribed, so guard their shape."""

    def test_every_row_matches_its_column_count(self) -> None:
        for entry in launch_benchmarks.LAUNCH_BENCHMARK_SETS:
            width = len(entry["columns"])
            for bench_id, label, _metric, values, _cond in entry["rows"]:
                with self.subTest(set_id=entry["set_id"], row=label):
                    self.assertEqual(len(values), width)
                    self.assertTrue(bench_id)

    def test_set_ids_and_snapshot_urls_are_unique(self) -> None:
        set_ids = [e["set_id"] for e in launch_benchmarks.LAUNCH_BENCHMARK_SETS]
        urls = [e["url"] for e in launch_benchmarks.LAUNCH_BENCHMARK_SETS]
        self.assertEqual(len(set_ids), len(set(set_ids)))
        self.assertEqual(len(urls), len(set(urls)))

    def test_sources_are_registered_ingestion_sources(self) -> None:
        for entry in launch_benchmarks.LAUNCH_BENCHMARK_SETS:
            with self.subTest(set_id=entry["set_id"]):
                self.assertIn(entry["source_id"], {"hf_model_card", "provider_blog"})
                self.assertTrue(entry["url"].startswith("https://"))
                self.assertTrue(entry.get("table_notes"))

    def test_every_benchmark_id_is_catalogued_or_explicitly_reused(self) -> None:
        known = set(launch_benchmarks.BENCHMARK_CATALOG) | set(
            launch_benchmarks.REUSED_BENCHMARK_IDS
        )
        for entry in launch_benchmarks.LAUNCH_BENCHMARK_SETS:
            for bench_id, label, *_ in entry["rows"]:
                with self.subTest(set_id=entry["set_id"], row=label):
                    self.assertIn(bench_id, known)

    def test_at_least_one_column_per_set_is_vendor_owned(self) -> None:
        for entry in launch_benchmarks.LAUNCH_BENCHMARK_SETS:
            with self.subTest(set_id=entry["set_id"]):
                self.assertTrue(any(c.get("model_slug") for c in entry["columns"]))

    def test_known_gaps_name_a_slug_and_a_revisit_path(self) -> None:
        for gap in launch_benchmarks.KNOWN_BENCHMARK_GAPS:
            with self.subTest(slug=gap["canonical_slug"]):
                self.assertIn("/", gap["canonical_slug"])
                self.assertTrue(gap["reason"])
                self.assertTrue(gap["revisit"])


if __name__ == "__main__":
    unittest.main()
