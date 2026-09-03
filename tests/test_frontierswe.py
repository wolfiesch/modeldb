from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.sources.frontierswe import FrontierSWEParser
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
        self.assertIsNotNone(records[1].parsed_fields_json)
        assert records[1].parsed_fields_json is not None
        inkling = json.loads(records[1].parsed_fields_json)
        self.assertEqual(inkling["rank"], 10)
        self.assertEqual(inkling["avg_cost_usd"], 9.15)
        self.assertEqual(inkling["avg_duration_hours"], 1.17)  # 70m converted to 1.17h
        self.assertEqual(inkling["vendor"], "Thinking Machines")

    def test_handles_empty_or_nonmatching_html_gracefully(self) -> None:
        records = list(FrontierSWEParser().parse(b"<html><body>No rows here</body></html>", snapshot_id=456))
        self.assertEqual(records, [])

    def test_source_is_in_recurring_m1_refresh_set(self) -> None:
        self.assertIn("frontierswe", M1_SOURCES)


if __name__ == "__main__":
    unittest.main()
