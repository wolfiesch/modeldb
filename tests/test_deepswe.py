from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingest.sources.deepswe import DeepSWEParser
from store.pipeline import M1_SOURCES


class DeepSWEParserTests(unittest.TestCase):
    def test_parses_all_leaderboard_variants_with_conditions_and_efficiency(self) -> None:
        payload = {
            "generated_at": "2026-07-11T00:00:00Z",
            "latest_job": {"name": "nightly", "finished_at": "2026-07-10T23:00:00Z"},
            "leaderboard": [
                {
                    "model": "gpt-5.6-sol",
                    "score": 72.7,
                    "ci": 3.0,
                    "config": "mini_swe_agent_gpt_5_6_sol_max",
                    "mean_cost_usd": 8.39,
                    "mean_duration_seconds": 1128.6,
                },
                {
                    "model": "gpt-5.6-luna",
                    "score": 67.2,
                    "config": "mini_swe_agent_gpt_5_6_luna_max",
                    "mean_cost_usd": 3.03,
                },
            ],
        }

        records = list(DeepSWEParser().parse(json.dumps(payload).encode(), snapshot_id=123))

        self.assertEqual([r.source_model_id for r in records], [
            "deepswe::mini-swe-agent-gpt-5-6-sol-max",
            "deepswe::mini-swe-agent-gpt-5-6-luna-max",
        ])
        sol = json.loads(records[0].parsed_fields_json)
        self.assertEqual(sol["benchmark_id"], "deepswe")
        self.assertEqual(sol["score"], 72.7)
        self.assertEqual(sol["ci"], 3.0)
        self.assertEqual(sol["config"], "mini_swe_agent_gpt_5_6_sol_max")
        self.assertEqual(sol["mean_cost_usd"], 8.39)
        self.assertEqual(sol["generated_at"], "2026-07-11T00:00:00Z")

    def test_skips_rows_without_model_or_score(self) -> None:
        payload = {"rows": [{"model": "gpt-5.6-sol"}, {"score": 50}, {"model": "gpt-5.6-sol", "score": 50}]}

        records = list(DeepSWEParser().parse(json.dumps(payload).encode(), snapshot_id=123))

        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].parsed_fields_json)["score"], 50.0)

    def test_source_is_in_recurring_m1_refresh_set(self) -> None:
        self.assertIn("deepswe", M1_SOURCES)


if __name__ == "__main__":
    unittest.main()
