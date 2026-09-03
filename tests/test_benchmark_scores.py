from __future__ import annotations

import unittest

from store.benchmark_scores import canonicalize_fractional_score, is_percentage_metric


class BenchmarkScoreUnitTests(unittest.TestCase):
    def test_fractional_percentage_metrics_become_percentage_points(self) -> None:
        self.assertAlmostEqual(canonicalize_fractional_score(0.3099173554, "percent_resolved"), 30.99173554)
        self.assertAlmostEqual(canonicalize_fractional_score(0.948, "accuracy"), 94.8)
        self.assertAlmostEqual(canonicalize_fractional_score(0.533, "percent"), 53.3)

        self.assertEqual(canonicalize_fractional_score(82.35, "accuracy"), 82.35)

    def test_non_percentage_metrics_preserve_their_scale(self) -> None:
        self.assertEqual(canonicalize_fractional_score(61.0, "index"), 61.0)
        self.assertEqual(canonicalize_fractional_score(1494.0, "elo"), 1494.0)

    def test_percentage_metric_detection_normalizes_spelling(self) -> None:
        self.assertTrue(is_percentage_metric("Percent correct"))
        self.assertTrue(is_percentage_metric("pass-rate"))
        self.assertFalse(is_percentage_metric("mean_score"))


if __name__ == "__main__":
    unittest.main()
