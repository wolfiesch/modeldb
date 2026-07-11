from __future__ import annotations

import sqlite3
import unittest


class PriceIntervalRepairTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE price_component (
                id INTEGER PRIMARY KEY,
                model_id INTEGER,
                provider_surface_id INTEGER,
                source_id TEXT,
                component TEXT NOT NULL,
                unit TEXT NOT NULL,
                currency TEXT NOT NULL,
                amount REAL NOT NULL,
                normalized_usd_per_1m_tokens REAL,
                tier_condition_json TEXT,
                valid_from TEXT,
                valid_to TEXT,
                source_snapshot_id INTEGER
            );
            CREATE TABLE source_snapshot (
                id INTEGER PRIMARY KEY,
                fetched_at TEXT NOT NULL
            );
            """
        )

    def _insert(self, identifier: int, *, amount: float = 1.0, snapshot: int = 1, valid_from: str = "2026-01-01T00:00:00+00:00") -> None:
        self.conn.execute(
            """
            INSERT INTO price_component
              (id, model_id, provider_surface_id, source_id, component, unit, currency,
               amount, normalized_usd_per_1m_tokens, tier_condition_json, valid_from, valid_to,
               source_snapshot_id)
            VALUES (?, 1, 10, 'models_dev', 'input_token', '1m_tokens', 'USD', ?, ?, NULL, ?, NULL, ?)
            """,
            (identifier, amount, amount, valid_from, snapshot),
        )


    def test_interval_repair_bounds_conflicting_cross_snapshot_observations(self) -> None:
        from store.price_intervals import repair_price_intervals

        self.conn.executemany(
            "INSERT INTO source_snapshot (id, fetched_at) VALUES (?, ?)",
            [
                (100, "2026-01-01T00:00:00+00:00"),
                (101, "2026-02-01T00:00:00+00:00"),
            ],
        )
        self._insert(1, amount=1.0, snapshot=100, valid_from="2026-01-01T00:00:00+00:00")
        self._insert(2, amount=2.0, snapshot=101, valid_from="2026-02-01T00:00:00+00:00")

        result = repair_price_intervals(self.conn)

        self.assertEqual(result["bounded_components"], 1)
        self.assertEqual(
            self.conn.execute("SELECT id, valid_from, valid_to FROM price_component ORDER BY id").fetchall(),
            [
                (1, "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
                (2, "2026-02-01T00:00:00+00:00", None),
            ],
        )
    def test_repair_merges_overlapping_identical_facts_and_preserves_all_snapshot_links(self) -> None:
        from store.price_intervals import repair_exact_price_duplicates

        self._insert(1, snapshot=100, valid_from="2026-01-01T00:00:00+00:00")
        self._insert(2, snapshot=101, valid_from="2026-01-02T00:00:00+00:00")

        result = repair_exact_price_duplicates(self.conn)

        self.assertEqual(result, {"merged_components": 1, "removed_components": 1, "observation_links": 2})
        self.assertEqual(
            self.conn.execute("SELECT id, valid_from, valid_to, source_snapshot_id FROM price_component").fetchall(),
            [(1, "2026-01-01T00:00:00+00:00", None, 100)],
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT price_component_id, source_snapshot_id FROM price_component_observation ORDER BY source_snapshot_id"
            ).fetchall(),
            [(1, 100), (1, 101)],
        )

    def test_repair_keeps_conflicting_amount_observations_separate(self) -> None:
        from store.price_intervals import repair_exact_price_duplicates

        self._insert(1, amount=1.0, snapshot=100)
        self._insert(2, amount=2.0, snapshot=101)

        result = repair_exact_price_duplicates(self.conn)

        self.assertEqual(result, {"merged_components": 0, "removed_components": 0, "observation_links": 2})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM price_component").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM price_component_observation").fetchone()[0], 2)

    def test_repair_is_idempotent(self) -> None:
        from store.price_intervals import repair_exact_price_duplicates

        self._insert(1, snapshot=100)
        self._insert(2, snapshot=101)

        repair_exact_price_duplicates(self.conn)
        result = repair_exact_price_duplicates(self.conn)
        self.assertEqual(result, {"merged_components": 0, "removed_components": 0, "observation_links": 2})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM price_component").fetchone()[0], 1)




    def test_repair_remains_effective_when_a_promotion_reinserts_an_observation(self) -> None:
        from store.price_intervals import repair_exact_price_duplicates

        self._insert(1, snapshot=100)
        self._insert(2, snapshot=101)
        repair_exact_price_duplicates(self.conn)
        self._insert(3, snapshot=102, valid_from="2026-01-03T00:00:00+00:00")

        result = repair_exact_price_duplicates(self.conn)

        self.assertEqual(result["removed_components"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM price_component").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT source_snapshot_id FROM price_component_observation ORDER BY 1").fetchall(),
            [(100,), (101,), (102,)],
        )
