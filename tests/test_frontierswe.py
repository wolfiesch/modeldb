from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.sources.frontierswe import FrontierSWEParser
from store.frontierswe import promote_frontierswe
from store.pipeline import M1_SOURCES


FIXTURE_HTML = """
<div title="Anthropic Claude Fable 5.1 + proximus: mean@5 56.3%, worst@5 44.5%, best@5 66.7%" class="grid items-center gap-x-3 grid-cols-[1.5rem_1.75rem_1fr_3.75rem]">
  <span class="text-[11px] tabular-nums text-neutral-500">1</span>
  <div class="truncate text-sm text-foreground font-heading">Claude Fable 5.1</div>
  <div class="truncate text-[10px] uppercase tracking-[0.08em] text-neutral-500">proximus</div>
  <div class="text-sm font-bold text-foreground">56.3<!-- -->%</div>
  <span>±<!-- -->11.1</span>
  <span class="hidden text-right text-xs tabular-nums text-neutral-400 md:block">$138.55</span>
  <span class="hidden text-right text-xs tabular-nums text-neutral-400 md:block">11.6h</span>
</div>
<div class="relative h-5">separator</div>
<div title="Thinking Machines Inkling + proximus: mean@5 4.1%, worst@5 0.1%, best@5 10.8%" class="grid items-center gap-x-3 grid-cols-[1.5rem_1.75rem_1fr_3.75rem]">
  <span class="text-[11px] tabular-nums text-neutral-500">10</span>
  <div class="truncate text-sm text-foreground font-heading">Inkling</div>
  <div class="truncate text-[10px] uppercase tracking-[0.08em] text-neutral-500">proximus</div>
  <div class="text-sm text-neutral-300">4.1<!-- -->%</div>
  <span>±<!-- -->5.3</span>
  <span class="hidden text-right text-xs tabular-nums text-neutral-400 md:block">$9.15</span>
  <span class="hidden text-right text-xs tabular-nums text-neutral-400 md:block">70m</span>
</div>
<div class="relative h-5">separator</div>
"""


class FrontierSWEParserTests(unittest.TestCase):
    def test_parses_leaderboard_rows_with_ranks_costs_and_whiskers(self) -> None:
        records = list(FrontierSWEParser().parse(FIXTURE_HTML.encode(), snapshot_id=456))
        self.assertEqual(len(records), 2)

        self.assertEqual(
            [r.source_model_id for r in records],
            ["frontierswe_v2::claude-fable-5-1", "frontierswe_v2::inkling"],
        )
        self.assertIsNotNone(records[0].parsed_fields_json)
        assert records[0].parsed_fields_json is not None
        fable = json.loads(records[0].parsed_fields_json)
        self.assertEqual(fable["benchmark_id"], "frontierswe_v2")
        self.assertEqual(fable["score"], 56.3)
        self.assertEqual(fable["worst_at_5"], 44.5)
        self.assertEqual(fable["best_at_5"], 66.7)
        self.assertEqual(fable["ci"], 11.1)
        self.assertEqual(fable["rank"], 1)
        self.assertEqual(fable["avg_cost_usd"], 138.55)
        self.assertEqual(fable["avg_duration_hours"], 11.6)
        self.assertEqual(fable["model_name"], "Claude Fable 5.1")
        self.assertEqual(fable["vendor"], "Anthropic")
        self.assertEqual(fable["harness"], "proximus")
        self.assertEqual(fable["n_tasks"], 34)
        self.assertEqual(fable["n_trials"], 5)
        self.assertEqual(fable["budget_hours"], 20)
        # Verify measured_at is not hardcoded to launch date
        self.assertIsNone(fable["measured_at"])

        self.assertIsNotNone(records[1].parsed_fields_json)
        assert records[1].parsed_fields_json is not None
        inkling = json.loads(records[1].parsed_fields_json)
        self.assertEqual(inkling["rank"], 10)
        self.assertEqual(inkling["avg_cost_usd"], 9.15)
        self.assertEqual(inkling["avg_duration_hours"], 1.17)
        self.assertEqual(inkling["vendor"], "Thinking Machines")
        self.assertIsNone(inkling["measured_at"])

    def test_handles_empty_or_nonmatching_html_gracefully(self) -> None:
        records = list(FrontierSWEParser().parse(b"<html><body>No rows here</body></html>", snapshot_id=456))
        self.assertEqual(records, [])

    def test_source_is_in_recurring_m1_refresh_set(self) -> None:
        self.assertIn("frontierswe", M1_SOURCES)

    def test_fetch_fails_visibly_without_silent_fallbacks(self) -> None:
        with patch("ingest.sources.frontierswe.urlopen", side_effect=URLError("Network unreachable")):
            with self.assertRaises(RuntimeError) as ctx:
                FrontierSWEParser().fetch()
            self.assertIn("FrontierSWE live fetch failed", str(ctx.exception))

    def test_promotion_leaves_measured_at_null_when_source_publishes_no_date(self) -> None:
        conn = sqlite3.connect(":memory:")
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.execute(
            """INSERT INTO source (id, name, base_url, ingestion_class, auth_type, update_cadence)
               VALUES ('frontierswe', 'FrontierSWE', 'https://www.frontierswe.com/', 'C', 'none', 'maintained')"""
        )
        conn.execute(
            """INSERT INTO organization (id, display_name)
               VALUES ('anthropic', 'Anthropic')"""
        )
        conn.execute(
            """INSERT INTO model (id, canonical_slug, developer_id, display_name, created_at, updated_at)
               VALUES (1, 'anthropic/claude-fable-5.1', 'anthropic', 'Claude Fable 5.1',
                       '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO model_alias
                 (source_id, alias_string, alias_normalized, alias_kind, model_id, confidence,
                  first_seen_at, last_seen_at)
               VALUES ('frontierswe', 'Claude Fable 5.1', 'claude-fable-5-1', 'display_name', 1, 1.0,
                       '2026-09-01T00:00:00Z', '2026-09-01T00:00:00Z')"""
        )
        conn.execute(
            """INSERT INTO source_snapshot (id, source_id, url, fetched_at, content_hash, parser_version)
               VALUES (99, 'frontierswe', 'https://www.frontierswe.com/', '2026-10-15T14:30:00+00:00',
                       'hash123', '0.1.0')"""
        )
        parsed_fields = {
            "score": 56.3,
            "metric": "percent_resolved",
            "rank": 1,
            "model_name": "Claude Fable 5.1",
            "model_version": "Claude Fable 5.1",
            "provider_name": "Anthropic",
            "measured_at": None,
        }
        conn.execute(
            """INSERT INTO source_model_record
                 (source_snapshot_id, source_model_id, display_name, provider_name,
                  raw_record_json, parsed_fields_json)
               VALUES (99, 'frontierswe_v2::claude-fable-5-1', 'Claude Fable 5.1', 'Anthropic',
                       '{}', ?)""",
            (json.dumps(parsed_fields),),
        )
        conn.commit()

        summary = promote_frontierswe(conn)
        self.assertEqual(summary["results_inserted"], 1)
        self.assertEqual(summary["linked"], 1)

        row = conn.execute(
            "SELECT measured_at, score, model_id FROM benchmark_result WHERE benchmark_id = 'frontierswe_v2'"
        ).fetchone()
        self.assertIsNotNone(row)
        # Invariant: measured_at is strictly source-provided per docs/SCHEMA.md:272.
        # When the source publishes no measurement date, it must remain NULL rather than
        # inventing dates from snapshot fetch time (source_snapshot_id already tracks fetch time).
        self.assertIsNone(row[0])
        self.assertEqual(row[1], 56.3)
        self.assertEqual(row[2], 1)


if __name__ == "__main__":
    unittest.main()
