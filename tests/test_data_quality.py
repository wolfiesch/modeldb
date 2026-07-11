from __future__ import annotations

import io
import sqlite3
from contextlib import closing, redirect_stderr, redirect_stdout
import shutil

import tempfile
import unittest
from pathlib import Path

from store.quality_gates import run_checks
from store.quality_gates import main


class DataQualityGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "models.sqlite"
        self.raw_path = self.root / "raw" / "snapshot.json"
        self.raw_path.parent.mkdir()
        self.raw_path.write_text('{"models": []}', encoding="utf-8")
        self._create_database(self.db_path)

    def test_reports_orphan_benchmark_reference_as_blocker(self) -> None:
        self._insert_result(model_id=999, benchmark_id="known", snapshot_id=1)

        report = run_checks(self.db_path, raw_root=self.root)

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "orphan_benchmark_reference", "error"), 1)

    def test_reports_missing_benchmark_provenance_as_blocker(self) -> None:
        self._insert_result(model_id=1, benchmark_id="known", snapshot_id=None)

        report = run_checks(self.db_path, raw_root=self.root)

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "missing_benchmark_provenance", "error"), 1)

    def test_reports_duplicate_canonical_slugs_as_blocker(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO model (id, canonical_slug) VALUES (2, 'acme/example')")

        report = run_checks(self.db_path, raw_root=self.root)

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "duplicate_canonical_slug", "error"), 1)

    def test_reports_overlapping_active_price_intervals_as_blocker(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executemany(
                """INSERT INTO price_component
                   (id, model_id, provider_surface_id, component, tier_condition_json, valid_from, valid_to)
                   VALUES (?, 1, 10, 'input_token', '{"tier":"standard"}', ?, ?)""",
                [(1, "2026-01-01", "2026-06-01"), (2, "2026-05-01", None)],
            )

        report = run_checks(self.db_path, raw_root=self.root)

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "overlapping_active_price_interval", "error"), 1)

    def test_baseline_downgrades_unchanged_integrity_violation_to_warning(self) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executemany(
                """INSERT INTO price_component
                   (id, model_id, provider_surface_id, component, unit, currency, source_id,
                    tier_condition_json, valid_from, valid_to)
                   VALUES (?, 1, 10, 'input_token', '1m_tokens', 'USD', 'source-a',
                    '{"tier":"standard"}', ?, ?)""",
                [(1, "2026-01-01", "2026-06-01"), (2, "2026-05-01", None)],
            )
        baseline_path = self.root / "baseline.sqlite"
        shutil.copy2(self.db_path, baseline_path)

        report = run_checks(self.db_path, baseline_path=baseline_path, raw_root=self.root)

        self.assertFalse(report["blocked"])
        self.assertEqual(self._issue_count(report, "overlapping_active_price_interval", "warning"), 1)

    def test_baseline_keeps_new_integrity_violation_as_blocker(self) -> None:
        baseline_path = self.root / "baseline.sqlite"
        shutil.copy2(self.db_path, baseline_path)
        self._insert_result(model_id=999, benchmark_id="known", snapshot_id=1)

        report = run_checks(self.db_path, baseline_path=baseline_path, raw_root=self.root)

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "orphan_benchmark_reference", "error"), 1)

    def test_reports_missing_snapshot_raw_payload_as_blocker(self) -> None:
        self.raw_path.unlink()

        report = run_checks(self.db_path, raw_root=self.root)

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "missing_snapshot_raw_payload", "error"), 1)

    def test_blocks_catastrophic_benchmark_result_count_regression(self) -> None:
        baseline_path = self.root / "baseline.sqlite"
        self._create_database(baseline_path)
        with closing(sqlite3.connect(baseline_path)) as conn, conn:
            for identifier in range(1, 11):
                conn.execute(
                    """INSERT INTO benchmark_result
                       (id, model_id, benchmark_id, source_snapshot_id, raw_record_json)
                       VALUES (?, 1, 'known', 1, '{}')""",

                    (identifier,),
                )

        report = run_checks(
            self.db_path,
            baseline_path=baseline_path,
            raw_root=self.root,
            thresholds={"max_benchmark_result_drop_ratio": 0.5},
        )

        self.assertTrue(report["blocked"])
        self.assertEqual(self._issue_count(report, "catastrophic_benchmark_result_regression", "error"), 1)

    def test_warns_when_benchmark_eval_condition_is_unavailable(self) -> None:
        self._insert_result(model_id=1, benchmark_id="known", snapshot_id=1)

        report = run_checks(self.db_path, raw_root=self.root)

        self.assertFalse(report["blocked"])
        self.assertEqual(self._issue_count(report, "missing_benchmark_eval_condition", "warning"), 1)

    def test_cli_writes_full_report_file_without_dumping_issue_list(self) -> None:
        report_path = self.root / "quality-report.json"
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--db", str(self.db_path), "--raw-root", str(self.root), "--report-file", str(report_path)])

        self.assertEqual(exit_code, 0)
        self.assertTrue(report_path.is_file())
        self.assertIn('"issues"', report_path.read_text(encoding="utf-8"))
        self.assertNotIn('"issues"', stdout.getvalue())
        self.assertIn("data quality: 0 blocker(s), 0 warning(s)", stderr.getvalue())

    def _insert_result(self, *, model_id: int, benchmark_id: str, snapshot_id: int | None) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """INSERT INTO benchmark_result
                   (id, model_id, benchmark_id, source_snapshot_id, raw_record_json)
                   VALUES (1, ?, ?, ?, '{}')""",
                (model_id, benchmark_id, snapshot_id),
            )

    @staticmethod
    def _issue_count(report: dict[str, object], code: str, severity: str) -> int:
        issues = report["issues"]
        assert isinstance(issues, list)
        return sum(issue["code"] == code and issue["severity"] == severity for issue in issues)

    @staticmethod
    def _create_database(path: Path) -> None:
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE model (id INTEGER PRIMARY KEY, canonical_slug TEXT NOT NULL);
                CREATE TABLE benchmark (id TEXT PRIMARY KEY);
                CREATE TABLE source_snapshot (id INTEGER PRIMARY KEY, url TEXT NOT NULL, raw_path TEXT);
                CREATE TABLE benchmark_result (
                    id INTEGER PRIMARY KEY,
                    model_id INTEGER,
                    benchmark_id TEXT,
                    source_snapshot_id INTEGER,
                    raw_record_json TEXT,
                    eval_condition_json TEXT
                );
                CREATE TABLE price_component (
                    id INTEGER PRIMARY KEY,
                    model_id INTEGER,
                    provider_surface_id INTEGER,
                    component TEXT NOT NULL,
                    tier_condition_json TEXT,
                    unit TEXT,
                    currency TEXT,
                    source_id TEXT,
                    valid_from TEXT,
                    valid_to TEXT
                );
                INSERT INTO model (id, canonical_slug) VALUES (1, 'acme/example');
                INSERT INTO benchmark (id) VALUES ('known');
                INSERT INTO source_snapshot (id, url, raw_path) VALUES (1, 'https://example.test/data', 'raw/snapshot.json');
                """
            )


if __name__ == "__main__":
    unittest.main()
