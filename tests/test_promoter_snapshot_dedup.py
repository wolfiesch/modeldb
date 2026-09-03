from __future__ import annotations

import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from store.benchmarks import promote_benchmarks
from store.capabilities import promote_capabilities
from store.prices import promote_prices

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "db" / "schema.sql"

SEED_SQL = """
INSERT INTO source (id, name) VALUES ('epoch', 'Epoch AI'), ('models_dev', 'models.dev'),
                                     ('openrouter', 'OpenRouter');
INSERT INTO model (id, canonical_slug, created_at, updated_at)
  VALUES (1, 'openai/gpt-5', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
INSERT INTO model_alias
  (source_id, alias_string, alias_normalized, alias_kind, model_id, confidence, first_seen_at, last_seen_at)
VALUES
  ('epoch', 'gpt-5_2025-08-07_high', 'gpt-5-2025-08-07-high', 'arena_model', 1, 1.0,
   '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
  ('models_dev', 'openai/gpt-5', 'gpt-5', 'api_model_id', 1, 1.0,
   '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
  ('openrouter', 'openai/gpt-5', 'gpt-5', 'router_id', 1, 1.0,
   '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
"""


def _connect_memory() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.executescript(SEED_SQL)
    return conn


def _snapshot(conn: sqlite3.Connection, snapshot_id: int, source_id: str) -> None:
    conn.execute(
        """INSERT INTO source_snapshot (id, source_id, url, fetched_at, content_hash, parser_version)
           VALUES (?, ?, ?, ?, ?, '0.1.0')""",
        (snapshot_id, source_id, f"https://{source_id}.test/", f"2026-07-{snapshot_id:02d}T00:00:00+00:00",
         f"hash{snapshot_id}"),
    )


def _record(conn: sqlite3.Connection, snapshot_id: int, source_model_id: str, parsed: dict) -> None:
    conn.execute(
        """INSERT INTO source_model_record
             (source_snapshot_id, source_model_id, raw_record_json, parsed_fields_json)
           VALUES (?, ?, '{}', ?)""",
        (snapshot_id, source_model_id, json.dumps(parsed)),
    )


class BenchmarkPromoterSnapshotDedupTests(unittest.TestCase):
    def test_promotes_only_the_newest_snapshot_per_source(self) -> None:
        with closing(_connect_memory()) as conn:
            parsed = {"benchmark_id": "gpqa_diamond", "score": 0.71, "stderr": 0.01,
                      "model_version": "gpt-5", "release_date": "2025-08-07"}
            _snapshot(conn, 1, "epoch")
            _snapshot(conn, 2, "epoch")
            _record(conn, 1, "gpt-5_2025-08-07_high", parsed)
            _record(conn, 2, "gpt-5_2025-08-07_high", parsed)

            summary = promote_benchmarks(conn)

            self.assertEqual(summary["results_inserted"], 1)
            rows = conn.execute(
                "SELECT source_snapshot_id FROM benchmark_result"
            ).fetchall()
            self.assertEqual(rows, [(2,)])

    def test_repromotion_replaces_stale_rows_from_older_snapshots(self) -> None:
        with closing(_connect_memory()) as conn:
            _snapshot(conn, 1, "epoch")
            _snapshot(conn, 2, "epoch")
            _record(conn, 2, "gpt-5_2025-08-07_high",
                    {"benchmark_id": "gpqa_diamond", "score": 0.71,
                     "model_version": "gpt-5", "release_date": "2025-08-07"})
            conn.execute("INSERT INTO benchmark (id, name) VALUES ('gpqa_diamond', 'GPQA Diamond')")
            conn.execute(
                """INSERT INTO benchmark_result
                     (model_id, benchmark_id, score, eval_condition_json, source_snapshot_id)
                   VALUES (1, 'gpqa_diamond', 0.71, '{}', 1)"""
            )

            promote_benchmarks(conn)

            rows = conn.execute("SELECT source_snapshot_id FROM benchmark_result").fetchall()
            self.assertEqual(rows, [(2,)])


class PricePromoterSnapshotDedupTests(unittest.TestCase):
    def test_promotes_only_the_newest_snapshot_per_source(self) -> None:
        with closing(_connect_memory()) as conn:
            _snapshot(conn, 1, "models_dev")
            _snapshot(conn, 2, "models_dev")
            _snapshot(conn, 3, "openrouter")
            _snapshot(conn, 4, "openrouter")
            _record(conn, 1, "openai/gpt-5", {"cost_input": 3, "cost_output": 15})
            _record(conn, 2, "openai/gpt-5", {"cost_input": 3, "cost_output": 15})
            _record(conn, 3, "openai/gpt-5", {"price_prompt": 0.000003, "price_completion": 0.000015})
            _record(conn, 4, "openai/gpt-5", {"price_prompt": 0.000003, "price_completion": 0.000015})

            summary = promote_prices(conn)

            rows = conn.execute(
                """SELECT source_id, component, COUNT(*), MIN(source_snapshot_id), MAX(source_snapshot_id)
                   FROM price_component GROUP BY source_id, component ORDER BY source_id, component"""
            ).fetchall()
            self.assertEqual(summary["inserted"], 4)
            self.assertEqual(
                rows,
                [
                    ("models_dev", "input_token", 1, 2, 2),
                    ("models_dev", "output_token", 1, 2, 2),
                    ("openrouter", "input_token", 1, 4, 4),
                    ("openrouter", "output_token", 1, 4, 4),
                ],
            )

    def test_repromotion_does_not_fan_out_windows(self) -> None:
        with closing(_connect_memory()) as conn:
            _snapshot(conn, 1, "models_dev")
            _snapshot(conn, 2, "models_dev")
            _record(conn, 2, "openai/gpt-5", {"cost_input": 3})

            promote_prices(conn)
            promote_prices(conn)

            count = conn.execute(
                "SELECT COUNT(*) FROM price_component WHERE component = 'input_token'"
            ).fetchone()[0]
            self.assertEqual(count, 1)


class CapabilityPromoterSnapshotDedupTests(unittest.TestCase):
    def test_promotes_only_the_newest_snapshot_per_source(self) -> None:
        with closing(_connect_memory()) as conn:
            _snapshot(conn, 1, "models_dev")
            _snapshot(conn, 2, "models_dev")
            _snapshot(conn, 3, "openrouter")
            _snapshot(conn, 4, "openrouter")
            _record(conn, 1, "openai/gpt-5", {"context_limit": 200000})
            _record(conn, 2, "openai/gpt-5", {"context_limit": 200000})
            _record(conn, 3, "openai/gpt-5", {"context_length": 200000})
            _record(conn, 4, "openai/gpt-5", {"context_length": 400000})

            promote_capabilities(conn)

            rows = conn.execute(
                "SELECT capability, value, source_snapshot_id FROM model_capability ORDER BY capability"
            ).fetchall()
            self.assertEqual(
                rows,
                [("context_window", "200000", 2), ("context_window", "400000", 4)],
            )


if __name__ == "__main__":
    unittest.main()
