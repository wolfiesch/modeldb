from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store import launch_registry, spine

FIXTURE_ENTRY = {
    "canonical_slug": "acme/widget-2",
    "display_name": "Widget 2",
    "developer_id": "acme",
    "family": "widget",
    "generation": "2",
    "tier_or_variant": "pro",
    "parameter_scale": "10b-a1b",
    "training_role": "reasoning",
    "release_date": "2026-07-30",
    "knowledge_cutoff": "2026-03",
    "stability": "preview",
    "open_weights": True,
    "confidence": "verified",
    "aliases": (
        ("acme/widget-2", "api_model_id"),
        ("widget-2", "bare_name"),
        ("acme-ml/Widget-2", "hf_repo_id"),
    ),
    "evidence": {
        "source_url": "https://acme.example/news/widget-2",
        "release_date": "2026-07-30",
        "vendor_claims": "beats everything; self-reported.",
    },
}

PRICED_ENTRY = {
    "canonical_slug": "globus/flare-1",
    "display_name": "Flare 1",
    "developer_id": "globus",
    "family": "flare",
    "generation": "1",
    "tier_or_variant": "flagship",
    "training_role": "reasoning",
    "release_date": "2026-09-02",
    "open_weights": False,
    "confidence": "verified",
    "aliases": (("flare-1", "bare_name"),),
    "evidence": {
        "source_url": "https://globus.example/flare-1",
        "release_date": "2026-09-02",
        "pricing_introductory": {"input_per_1m": 0.75, "output_per_1m": 3.75},
        "pricing_post_intro": {
            "input_per_1m": 1.50, "output_per_1m": 7.50, "effective_date": "2027-01-01",
        },
        "pricing_per_second": {"720p_usd": 0.10},
        "context_window": 262144,
        "max_output": 65536,
    },
}


class LaunchRegistryPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
        self.conn.executescript(schema_path.read_text())
        self.conn.execute(
            "INSERT INTO source (id, name, ingestion_class, auth_type) VALUES "
            "('models_dev','models.dev','A','none'),"
            "('provider_blog','provider blog','C','none')"
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patcher in (
            mock.patch.object(launch_registry, "LAUNCH_ENTRIES", (FIXTURE_ENTRY,)),
            mock.patch("store.announcement.REPO_ROOT", Path(tmp.name)),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_promote_mints_row_aliases_and_snapshot(self) -> None:
        summary = launch_registry.promote_launch_registry(self.conn)

        self.assertEqual(summary["models_created"], 1)
        self.assertEqual(summary["aliases_created"], 3)
        self.assertEqual(summary["snapshots_created"], 1)

        row = self.conn.execute(
            "SELECT developer_id, family, generation, tier_or_variant, parameter_scale, "
            "training_role, release_date, snapshot_date, knowledge_cutoff, stability, "
            "open_weights, canonical_confidence, display_name "
            "FROM model WHERE canonical_slug='acme/widget-2'"
        ).fetchone()
        self.assertEqual(
            row,
            ("acme", "widget", "2", "pro", "10b-a1b", "reasoning", "2026-07-30",
             "2026-07-30", "2026-03", "preview", 1, "verified", "Widget 2"),
        )
        self.assertIsNotNone(
            self.conn.execute("SELECT 1 FROM organization WHERE id='acme'").fetchone()
        )

    def test_promote_is_idempotent(self) -> None:
        launch_registry.promote_launch_registry(self.conn)
        second = launch_registry.promote_launch_registry(self.conn)

        self.assertEqual(second["models_created"], 0)
        self.assertEqual(second["aliases_created"], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM model").fetchone()[0], 1)
        # 3 registry aliases + the display-name alias written by the evidence capture
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM model_alias").fetchone()[0], 4
        )

    def test_promotes_evidence_prices_with_validity_windows(self) -> None:
        for patcher in (mock.patch.object(launch_registry, "LAUNCH_ENTRIES", (PRICED_ENTRY,)),):
            patcher.start()
            self.addCleanup(patcher.stop)
        summary = launch_registry.promote_launch_registry(self.conn)

        self.assertEqual(summary["prices_created"], 4)
        self.assertEqual(summary["capabilities_created"], 2)

        rows = self.conn.execute(
            "SELECT component, amount, valid_from, valid_to, tier_condition_json "
            "FROM price_component WHERE source_id='provider_blog' "
            "ORDER BY component, valid_from"
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("input_token", 0.75, "2026-09-02", "2026-12-31", None),
                ("input_token", 1.50, "2027-01-01", None, None),
                ("output_token", 3.75, "2026-09-02", "2026-12-31", None),
                ("output_token", 7.50, "2027-01-01", None, None),
            ],
        )
        # Non-token pricing never becomes a row.
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM price_component WHERE unit != '1m_tokens'"
            ).fetchone()[0], 0,
        )
        caps = self.conn.execute(
            "SELECT capability, value FROM model_capability ORDER BY capability"
        ).fetchall()
        self.assertEqual(caps, [("context_window", "262144"), ("max_output", "65536")])

    def test_price_promotion_is_idempotent_across_runs(self) -> None:
        for patcher in (mock.patch.object(launch_registry, "LAUNCH_ENTRIES", (PRICED_ENTRY,)),):
            patcher.start()
            self.addCleanup(patcher.stop)
        launch_registry.promote_launch_registry(self.conn)
        second = launch_registry.promote_launch_registry(self.conn)

        self.assertEqual(second["prices_created"], 4)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM price_component WHERE source_id='provider_blog'"
            ).fetchone()[0], 4,
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM model_capability").fetchone()[0], 2
        )

    def test_intro_then_standard_window_uses_day_after(self) -> None:
        entry = {
            **PRICED_ENTRY,
            "release_date": "2026-08-01",
            "evidence": {
                **PRICED_ENTRY["evidence"],
                "release_date": "2026-08-01",
                "pricing_introductory": None,
                "pricing_post_intro": None,
                "pricing_intro": {"input_per_1m": 2, "output_per_1m": 10, "through": "2026-08-31"},
                "pricing_standard": {"input_per_1m": 3, "output_per_1m": 15},
            },
        }
        for patcher in (mock.patch.object(launch_registry, "LAUNCH_ENTRIES", (entry,)),):
            patcher.start()
            self.addCleanup(patcher.stop)
        launch_registry.promote_launch_registry(self.conn)

        rows = self.conn.execute(
            "SELECT component, amount, valid_from, valid_to FROM price_component "
            "WHERE source_id='provider_blog' ORDER BY component, valid_from"
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("input_token", 2.0, "2026-08-01", "2026-08-31"),
                ("input_token", 3.0, "2026-09-01", None),
                ("output_token", 10.0, "2026-08-01", "2026-08-31"),
                ("output_token", 15.0, "2026-09-01", None),
            ],
        )

    def test_registry_row_is_resolvable_by_link_model(self) -> None:
        launch_registry.promote_launch_registry(self.conn)
        model_id = self.conn.execute(
            "SELECT id FROM model WHERE canonical_slug='acme/widget-2'"
        ).fetchone()[0]

        # Later catalog snapshots must land their facts on the registry row instead of
        # a second identity: this is what makes prices and benchmarks flow in.
        self.assertEqual(
            spine.link_model(
                self.conn, source_id="openrouter", source_model_id="acme/widget-2",
                parsed_fields={"hugging_face_id": "acme-ml/Widget-2"},
            ),
            model_id,
        )
        self.assertEqual(
            spine.link_model(
                self.conn, source_id="models_dev", source_model_id="vercel/acme/widget-2",
                parsed_fields={},
            ),
            model_id,
        )

    def test_build_spine_does_not_duplicate_a_registry_row(self) -> None:
        launch_registry.promote_launch_registry(self.conn)
        snapshot_id = self.conn.execute(
            "INSERT INTO source_snapshot (source_id, url, fetched_at, content_hash, "
            "parser_version) VALUES ('models_dev','https://models.dev/api.json',"
            "'2026-08-03T00:00:00Z','h','test')"
        ).lastrowid
        # `vercel` re-exports; it must attach an alias rather than mint a second row.
        self.conn.execute(
            "INSERT INTO source_model_record (source_snapshot_id, source_model_id, "
            "display_name, raw_record_json, parsed_fields_json) VALUES "
            "(?,'vercel/acme/widget-2','Widget 2','{}',?)",
            (snapshot_id, json.dumps({"release_date": "2026-07-30"})),
        )

        spine.build_spine(self.conn)

        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM model WHERE canonical_slug LIKE '%widget-2'"
            ).fetchone()[0],
            1,
        )


class ShippedRegistryContentTests(unittest.TestCase):
    """The shipped entries are hand-written, so guard their shape."""

    def test_slugs_are_unique(self) -> None:
        slugs = [entry["canonical_slug"] for entry in launch_registry.LAUNCH_ENTRIES]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_entries_are_well_formed(self) -> None:
        for entry in launch_registry.LAUNCH_ENTRIES:
            with self.subTest(slug=entry["canonical_slug"]):
                self.assertTrue(
                    entry["canonical_slug"].startswith(entry["developer_id"] + "/"),
                    "canonical_slug must be prefixed with its developer id",
                )
                self.assertTrue(entry["display_name"])
                self.assertRegex(entry["release_date"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertIn(
                    entry.get("confidence", "probable"),
                    {"verified", "probable", "manual_review"},
                )
                self.assertTrue(entry["evidence"]["source_url"].startswith("https://"))
                self.assertTrue(entry["aliases"], "an entry needs at least one alias")
                for alias_string, alias_kind in entry["aliases"]:
                    self.assertTrue(alias_string.strip())
                    self.assertTrue(alias_kind.strip())

    def test_alias_pairs_are_unique_per_entry(self) -> None:
        for entry in launch_registry.LAUNCH_ENTRIES:
            with self.subTest(slug=entry["canonical_slug"]):
                aliases = list(entry["aliases"])
                self.assertEqual(len(aliases), len(set(aliases)))


if __name__ == "__main__":
    unittest.main()
