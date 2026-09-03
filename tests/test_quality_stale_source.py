from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from store.quality_gates import run_checks

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


class StaleSourceWarningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db_path = self.root / "models.sqlite"
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _add_source(self, source_id: str, cadence: str) -> None:
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "INSERT INTO source (id, name, update_cadence) VALUES (?, ?, ?)",
                (source_id, source_id, cadence),
            )

    def _add_snapshot(self, source_id: str, fetched_at: str) -> None:
        raw_rel = f"raw/{source_id}.json"
        (self.root / "raw").mkdir(exist_ok=True)
        (self.root / raw_rel).write_text("{}", encoding="utf-8")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """INSERT INTO source_snapshot (source_id, url, fetched_at, content_hash, parser_version, raw_path)
                   VALUES (?, 'https://example.test/', ?, 'h', '0.1.0', ?)""",
                (source_id, fetched_at, raw_rel),
            )

    def _issue_count(self, report: dict, code: str) -> tuple[int, int]:
        issues = report["issues"]
        return (
            sum(i["code"] == code and i["severity"] == "warning" for i in issues),
            sum(i["code"] == code and i["severity"] == "error" for i in issues),
        )

    def test_fresh_scheduled_source_does_not_warn(self) -> None:
        self._add_source("models_dev", "hourly sync")
        self._add_snapshot("models_dev", datetime.now(timezone.utc).isoformat())

        report = run_checks(self.db_path, raw_root=self.root)

        warnings, errors = self._issue_count(report, "stale_source")
        self.assertEqual((warnings, errors), (0, 0))

    def test_stale_scheduled_source_warns_without_blocking(self) -> None:
        self._add_source("openrouter", "live")
        self._add_snapshot(
            "openrouter",
            (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(),
        )

        report = run_checks(self.db_path, raw_root=self.root)

        warnings, errors = self._issue_count(report, "stale_source")
        self.assertEqual((warnings, errors), (1, 0))
        self.assertFalse(report["blocked"])

    def test_scheduled_source_without_any_snapshot_warns(self) -> None:
        self._add_source("epoch", "daily")

        report = run_checks(self.db_path, raw_root=self.root)

        warnings, _ = self._issue_count(report, "stale_source")
        self.assertEqual(warnings, 1)

    def test_weekly_cadence_uses_generous_multiplier(self) -> None:
        self._add_source("weekly_src", "weekly")
        # 20 days is inside the generous 3x (21d) window: no warning yet.
        self._add_snapshot("weekly_src", (datetime.now(timezone.utc) - timedelta(days=20)).isoformat())

        report = run_checks(self.db_path, raw_root=self.root)

        warnings, _ = self._issue_count(report, "stale_source")
        self.assertEqual(warnings, 0)

    def test_unscheduled_cadences_never_warn(self) -> None:
        self._add_source("swebench", "maintained")
        self._add_source("open_llm_lb", "FROZEN 2025-03")
        self._add_source("vllm", "per-release")

        report = run_checks(self.db_path, raw_root=self.root)

        warnings, _ = self._issue_count(report, "stale_source")
        self.assertEqual(warnings, 0)


if __name__ == "__main__":
    unittest.main()
