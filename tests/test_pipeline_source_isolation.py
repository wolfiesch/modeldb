from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import ingest.run
import store.pipeline
from ingest.run import main
from store.pipeline import run_pipeline

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"


def _make_temp_db(root: Path) -> Path:
    db_path = root / "models.sqlite"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.executescript((Path(__file__).resolve().parents[1] / "db" / "seed_sources.sql").read_text(encoding="utf-8"))
    return db_path


class PipelineSourceIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db_path = _make_temp_db(self.root)

        def fake_connect(_path=None):
            connection = sqlite3.connect(self.db_path)
            connection.execute("PRAGMA foreign_keys = ON")
            return connection

        connect_patch = patch.object(store.pipeline, "connect", fake_connect)
        connect_patch.start()
        self.addCleanup(connect_patch.stop)

    def _patch_registry(self, run_source_side_effect):
        registry_patch = patch.object(
            store.pipeline, "build_registry", return_value=({"models_dev": object, "openrouter": object}, {})
        )
        registry_patch.start()
        self.addCleanup(registry_patch.stop)
        run_patch = patch.object(store.pipeline, "run_source", side_effect=run_source_side_effect)
        run_patch.start()
        self.addCleanup(run_patch.stop)

    def test_source_exception_is_recorded_and_pipeline_continues(self) -> None:
        def run_source(source_id, cls, conn):
            if source_id == "openrouter":
                raise RuntimeError("boom")
            return f"{source_id}: snapshot_id=1 records=5"

        self._patch_registry(run_source)

        summary = run_pipeline(fetch=True)

        self.assertIn("models_dev: snapshot_id=1 records=5", summary["ingest"])
        self.assertIn("openrouter: FAILED (boom)", summary["ingest"])
        # Later stages still ran against the same connection.
        self.assertIn("spine", summary)
        self.assertIn("benchmarks", summary)

    def test_all_sources_failing_still_completes_the_run(self) -> None:
        def run_source(source_id, cls, conn):
            raise RuntimeError(f"{source_id} down")

        self._patch_registry(run_source)

        summary = run_pipeline(fetch=True)

        failed = [line for line in summary["ingest"] if ": FAILED (" in line]
        unavailable = [line for line in summary["ingest"] if ": unavailable (" in line]
        attempted = ("models_dev", "openrouter")
        self.assertEqual(len(failed), len(attempted))
        self.assertEqual(
            len(unavailable), len(store.pipeline.M1_SOURCES) - len(attempted)
        )
        self.assertIn("spine", summary)

    def test_unavailable_sources_are_reported_without_failing_the_run(self) -> None:
        registry_patch = patch.object(
            store.pipeline, "build_registry", return_value=({"models_dev": object}, {"openrouter": "ImportError: nope"})
        )
        registry_patch.start()
        self.addCleanup(registry_patch.stop)
        run_patch = patch.object(store.pipeline, "run_source", return_value="models_dev: snapshot_id=1 records=2")
        run_patch.start()
        self.addCleanup(run_patch.stop)

        summary = run_pipeline(fetch=True)

        self.assertIn("openrouter: unavailable (ImportError: nope)", summary["ingest"])
        self.assertIn("models_dev: snapshot_id=1 records=2", summary["ingest"])


class IngestCliIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.db_path = _make_temp_db(self.root)
        def fake_connect(_path=None):
            return sqlite3.connect(self.db_path)

        connect_patch = patch.object(ingest.run, "connect", fake_connect)
        connect_patch.start()
        self.addCleanup(connect_patch.stop)

    def _patch_registry(self, registry):
        registry_patch = patch.object(ingest.run, "build_registry", return_value=(registry, {}))
        registry_patch.start()
        self.addCleanup(registry_patch.stop)

    def test_partial_failure_exits_zero_and_prints_failed_line(self) -> None:
        self._patch_registry({"models_dev": object, "openrouter": object})

        def run_source(source_id, cls, conn):
            if source_id == "openrouter":
                raise RuntimeError("nope")
            return f"{source_id}: snapshot_id=1 records=1"

        with patch.object(ingest.run, "run_source", side_effect=run_source):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["all"])

        self.assertEqual(exit_code, 0)
        self.assertIn("openrouter: FAILED (nope)", stdout.getvalue())
        self.assertIn("models_dev: snapshot_id=1 records=1", stdout.getvalue())

    def test_every_source_failing_exits_one(self) -> None:
        self._patch_registry({"models_dev": object, "openrouter": object})

        def run_source(source_id, cls, conn):
            raise RuntimeError(f"{source_id} down")

        with patch.object(ingest.run, "run_source", side_effect=run_source):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = main(["all"])

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue().count(": FAILED ("), 2)

    def test_single_failing_source_exits_one(self) -> None:
        self._patch_registry({"openrouter": object})

        def run_source(source_id, cls, conn):
            raise RuntimeError("nope")

        with patch.object(ingest.run, "run_source", side_effect=run_source):
            with redirect_stdout(io.StringIO()):
                exit_code = main(["openrouter"])

        self.assertEqual(exit_code, 1)

    def test_single_ok_source_exits_zero(self) -> None:
        self._patch_registry({"openrouter": object})

        with patch.object(ingest.run, "run_source", return_value="openrouter: snapshot_id=1 records=1"):
            with redirect_stdout(io.StringIO()):
                exit_code = main(["openrouter"])

        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
