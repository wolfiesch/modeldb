from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import collect_omp_tps

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"

STUB_SPEEDTEST = """import json, os, sys
sys.stdout.write(open(os.environ["STUB_PAYLOAD"], encoding="utf-8").read())
sys.exit(int(os.environ["STUB_EXIT"]))
"""

MODEL_CONFIG = [
    {
        "key": "alpha",
        "label": "Alpha",
        "canonicalSlug": "vendor/alpha",
        "ompSelector": "stub/alpha",
        "providerLabel": "Stub",
    },
    {
        "key": "beta",
        "label": "Beta",
        "canonicalSlug": "vendor/beta",
        "ompSelector": "stub/beta",
        "providerLabel": "Stub",
    },
]


def _ok_record(selector: str) -> dict:
    return {
        "timestamp": "2026-08-02T09:54:14+00:00",
        "mode": "visible",
        "model": selector,
        "run": 1,
        "status": "ok",
        "exitCode": 0,
        "durationMs": 1000.0,
        "visibleTokens": 100,
        "visibleTokensPerSecond": 100.0,
        "visibleChars": 400,
        "visibleCharsPerSecond": 400.0,
        "tokenizer": "regex-v1",
    }


def _failed_record(selector: str) -> dict:
    return {
        "timestamp": "2026-08-02T09:55:14+00:00",
        "mode": "visible",
        "model": selector,
        "run": 1,
        "status": "error",
        "exitCode": 1,
        "durationMs": 500.0,
        "visibleTokens": 0,
        "visibleTokensPerSecond": 0.0,
        "visibleChars": 0,
        "visibleCharsPerSecond": 0.0,
        "tokenizer": "regex-v1",
        "stderr": '429 {"error":{"code":"1113","message":"Insufficient balance"}}',
    }


def _summary(selector: str, ok_runs: int) -> dict:
    return {
        "model": selector,
        "runs": 1,
        "okRuns": ok_runs,
        "failures": 1 - ok_runs,
        "averageVisibleTokensPerSecond": 100.0 if ok_runs else None,
        "medianVisibleTokensPerSecond": 100.0 if ok_runs else None,
        "p95VisibleTokensPerSecond": 100.0 if ok_runs else None,
        "medianDurationMs": 1000.0 if ok_runs else None,
    }


class CollectOmpTpsDegradedRunTests(unittest.TestCase):
    """A dead or unfunded selector must not block the publish pipeline."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.workdir = Path(self.tmpdir.name)
        self.db_path = self.workdir / "modeldb.sqlite"
        self._create_db()

        self.stub_path = self.workdir / "stub_speedtest.py"
        self.stub_path.write_text(STUB_SPEEDTEST, encoding="utf-8")
        self.config_path = self.workdir / "omp_tps_models.json"
        self.config_path.write_text(json.dumps(MODEL_CONFIG), encoding="utf-8")
        self.payload_path = self.workdir / "stub_payload.json"

        for target, value in (
            ("scripts.collect_omp_tps.SPEEDTEST", self.stub_path),
            ("scripts.collect_omp_tps.REPO_ROOT", self.workdir),
            ("ingest.base.REPO_ROOT", self.workdir),
            ("ingest.base.RAW_ROOT", self.workdir / "data" / "raw"),
            ("ingest.base.connect", self._connect),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _connect(self, db_path: Path | None = None) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path or self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            now = "2026-08-02T00:00:00+00:00"
            for slug in ("vendor/alpha", "vendor/beta"):
                conn.execute(
                    "INSERT INTO model (canonical_slug, created_at, updated_at) VALUES (?,?,?)",
                    (slug, now, now),
                )
            conn.commit()
        finally:
            conn.close()

    def _run(self, payload: dict, exit_code: int) -> tuple[int, str, str]:
        self.payload_path.write_text(json.dumps(payload), encoding="utf-8")
        env = {
            "OMP_TPS_ALLOW_PAID": "1",
            "STUB_PAYLOAD": str(self.payload_path),
            "STUB_EXIT": str(exit_code),
        }
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.dict("os.environ", env), redirect_stdout(stdout), redirect_stderr(stderr):
            code = collect_omp_tps.main(
                ["--config", str(self.config_path), "--runs", "1", "--timeout", "5"]
            )
        return code, stdout.getvalue(), stderr.getvalue()

    def _promoted_slugs(self) -> list[str]:
        conn = sqlite3.connect(self.db_path)
        try:
            return [
                row[0]
                for row in conn.execute(
                    """
                    SELECT m.canonical_slug
                    FROM benchmark_result br
                    JOIN model m ON m.id = br.model_id
                    ORDER BY m.canonical_slug
                    """
                )
            ]
        finally:
            conn.close()

    def _artifact_dir(self) -> Path:
        runs = sorted((self.workdir / ".perf" / "omp-tps").iterdir())
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_partial_failure_promotes_surviving_samples_and_keeps_evidence(self) -> None:
        payload = {
            "runs": 1,
            "prompt": "count",
            "models": [_summary("stub/alpha", 1), _summary("stub/beta", 0)],
            "records": [_ok_record("stub/alpha"), _failed_record("stub/beta")],
        }

        code, stdout, stderr = self._run(payload, exit_code=1)

        self.assertEqual(code, 0)
        self.assertEqual(self._promoted_slugs(), ["vendor/alpha"])
        self.assertEqual(json.loads(stdout)["inserted"], 1)
        self.assertIn("stub/beta", stderr)
        artifact_dir = self._artifact_dir()
        self.assertTrue((artifact_dir / "error.json").exists())
        stored = json.loads((artifact_dir / "payload.json").read_text(encoding="utf-8"))
        self.assertTrue(stored["degraded"])

    def test_total_failure_names_selectors_and_skips_promotion(self) -> None:
        payload = {
            "runs": 1,
            "prompt": "count",
            "models": [_summary("stub/alpha", 0), _summary("stub/beta", 0)],
            "records": [_failed_record("stub/alpha"), _failed_record("stub/beta")],
        }

        code, _stdout, stderr = self._run(payload, exit_code=1)

        self.assertEqual(code, 1)
        self.assertEqual(self._promoted_slugs(), [])
        self.assertIn("stub/alpha", stderr)
        self.assertIn("stub/beta", stderr)
        artifact_dir = self._artifact_dir()
        self.assertTrue((artifact_dir / "error.json").exists())
        self.assertFalse((artifact_dir / "payload.json").exists())

    def test_clean_run_is_not_marked_degraded(self) -> None:
        payload = {
            "runs": 1,
            "prompt": "count",
            "models": [_summary("stub/alpha", 1), _summary("stub/beta", 1)],
            "records": [_ok_record("stub/alpha"), _ok_record("stub/beta")],
        }

        code, stdout, _stderr = self._run(payload, exit_code=0)

        self.assertEqual(code, 0)
        self.assertEqual(self._promoted_slugs(), ["vendor/alpha", "vendor/beta"])
        self.assertEqual(json.loads(stdout)["inserted"], 2)
        artifact_dir = self._artifact_dir()
        self.assertFalse((artifact_dir / "error.json").exists())
        stored = json.loads((artifact_dir / "payload.json").read_text(encoding="utf-8"))
        self.assertFalse(stored["degraded"])


if __name__ == "__main__":
    unittest.main()
