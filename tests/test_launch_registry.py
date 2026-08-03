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
