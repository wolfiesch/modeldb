from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve import resolver


FROZEN_NOW = "2026-07-03T09:00:00+00:00"


class AcceptNewModelBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE source (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                base_url TEXT,
                ingestion_class TEXT,
                auth_type TEXT,
                update_cadence TEXT,
                notes TEXT
            );
            CREATE TABLE organization (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                country TEXT,
                aliases_json TEXT
            );
            CREATE TABLE model (
                id INTEGER PRIMARY KEY,
                canonical_slug TEXT UNIQUE NOT NULL,
                developer_id TEXT,
                family TEXT,
                generation TEXT,
                tier_or_variant TEXT,
                parameter_scale TEXT,
                training_role TEXT,
                release_date TEXT,
                snapshot_date TEXT,
                knowledge_cutoff TEXT,
                stability TEXT,
                open_weights INTEGER,
                display_name TEXT,
                canonical_confidence TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE model_alias (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                alias_string TEXT NOT NULL,
                alias_normalized TEXT NOT NULL,
                alias_kind TEXT NOT NULL,
                model_id INTEGER,
                provider_surface_id INTEGER,
                artifact_id INTEGER,
                valid_from TEXT,
                valid_to TEXT,
                resolution_method TEXT,
                confidence REAL NOT NULL DEFAULT 0,
                source_snapshot_id INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            );
            CREATE UNIQUE INDEX idx_alias_unique
                ON model_alias (source_id, alias_string, alias_kind, COALESCE(valid_from, ''));
            CREATE TABLE source_snapshot (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                etag TEXT,
                last_modified TEXT,
                parser_version TEXT NOT NULL,
                raw_path TEXT,
                UNIQUE (source_id, url, content_hash)
            );
            CREATE TABLE source_model_record (
                id INTEGER PRIMARY KEY,
                source_snapshot_id INTEGER NOT NULL,
                source_model_id TEXT NOT NULL,
                display_name TEXT,
                provider_name TEXT,
                raw_record_json TEXT NOT NULL,
                parsed_fields_json TEXT,
                model_alias_id INTEGER,
                UNIQUE (source_snapshot_id, source_model_id)
            );
            CREATE TABLE entity_resolution_queue (
                id INTEGER PRIMARY KEY,
                source_record_id INTEGER,
                candidate_model_id INTEGER,
                reason TEXT NOT NULL,
                features_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            INSERT INTO source (id, name, base_url, ingestion_class, auth_type, update_cadence, notes)
            VALUES ('artificialanalysis', 'Artificial Analysis', 'https://artificialanalysis.ai', 'B', 'api_key', 'daily', NULL);
            INSERT INTO organization (id, display_name, country, aliases_json)
            VALUES
                ('anthropic', 'Anthropic', 'US', '[]'),
                ('moonshotai', 'Moonshot AI', 'CN', '["moonshot"]');

            INSERT INTO model (
                id, canonical_slug, developer_id, family, generation, tier_or_variant,
                canonical_confidence, created_at, updated_at
            ) VALUES (
                1, 'anthropic/claude-sonnet-4.5', 'anthropic', 'claude', '4.5', 'sonnet',
                'verified', '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'
            );
            """
        )

    def test_valid_dry_run_reports_created_item_without_mutating_any_review_state(self) -> None:
        source_record_id = self._insert_source_record()
        queue_id = self._insert_queue_row(source_record_id)
        review = self._new_model_review(queue_id)
        before = self._state_snapshot()

        with patch.object(resolver, "utcnow", return_value=FROZEN_NOW):
            summary = resolver.accept_new_model_batch(self.conn, [review], dry_run=True)

        self.assertEqual(summary["created"], 1)
        self.assertIs(summary["dry_run"], True)
        self.assertEqual(len(summary["items"]), 1)
        self.assertEqual(summary["items"][0]["queue_id"], queue_id)
        self.assertEqual(summary["items"][0]["source_record_id"], source_record_id)
        self.assertEqual(summary["items"][0]["canonical_slug"], "moonshotai/kimi-k2-turbo")
        self.assertEqual(summary["items"][0]["developer_id"], "moonshotai")
        self.assertEqual(self._state_snapshot(), before)

    def test_real_run_creates_model_explicit_aliases_source_link_resolved_queue_and_audit(self) -> None:
        source_record_id = self._insert_source_record()
        queue_id = self._insert_queue_row(source_record_id)
        review = self._new_model_review(queue_id)

        with patch.object(resolver, "utcnow", return_value=FROZEN_NOW):
            summary = resolver.accept_new_model_batch(self.conn, [review], dry_run=False)

        self.assertEqual(summary["created"], 1)
        self.assertIs(summary["dry_run"], False)
        created_model_id = summary["items"][0]["model_id"]
        model = self.conn.execute(
            """
            SELECT canonical_slug, developer_id, canonical_confidence, created_at, updated_at
            FROM model
            WHERE id = ?
            """,
            (created_model_id,),
        ).fetchone()
        self.assertEqual(
            model,
            (
                "moonshotai/kimi-k2-turbo",
                "moonshotai",
                "manual_review",
                FROZEN_NOW,
                FROZEN_NOW,
            ),
        )
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM model WHERE id <> 1").fetchone()[0],
            1,
        )

        aliases = self.conn.execute(
            """
            SELECT id, source_id, alias_string, alias_normalized, alias_kind, model_id,
                   resolution_method, confidence, source_snapshot_id, first_seen_at, last_seen_at
            FROM model_alias
            ORDER BY alias_string
            """
        ).fetchall()
        self.assertEqual(
            [row[1:] for row in aliases],
            [
                (
                    "artificialanalysis",
                    "kimi-k2-turbo",
                    "kimi-k2-turbo",
                    "api_model_id",
                    created_model_id,
                    "manual_review",
                    1.0,
                    201,
                    FROZEN_NOW,
                    FROZEN_NOW,
                ),
                (
                    "artificialanalysis",
                    "moonshotai/kimi-k2-turbo",
                    "moonshotai-kimi-k2-turbo",
                    "api_model_id",
                    created_model_id,
                    "manual_review",
                    1.0,
                    201,
                    FROZEN_NOW,
                    FROZEN_NOW,
                ),
            ],
        )
        linked_alias_id = self.conn.execute(
            "SELECT model_alias_id FROM source_model_record WHERE id = ?",
            (source_record_id,),
        ).fetchone()[0]
        self.assertIn(linked_alias_id, {row[0] for row in aliases})
        self.assertEqual(
            self.conn.execute(
                """
                SELECT candidate_model_id, status, resolved_at
                FROM entity_resolution_queue
                WHERE id = ?
                """,
                (queue_id,),
            ).fetchone(),
            (created_model_id, "resolved", FROZEN_NOW),
        )

        audit_rows = self._audit_rows()
        self.assertEqual(len(audit_rows), 1)
        action, audit_queue_id, audit_source_record_id, audit_model_id, details_json = audit_rows[0]
        self.assertEqual((action, audit_queue_id, audit_source_record_id, audit_model_id), ("new_model", queue_id, source_record_id, created_model_id))
        details = json.loads(details_json)
        self.assertEqual(details["canonical_slug"], "moonshotai/kimi-k2-turbo")
        self.assertEqual(details["developer_id"], "moonshotai")
        self.assertEqual(details["aliases"], ["kimi-k2-turbo", "moonshotai/kimi-k2-turbo"])
        self.assertEqual(set(details["model_alias_ids"]), {row[0] for row in aliases})


    def test_reviewed_display_name_is_stored_on_created_model(self) -> None:
        source_record_id = self._insert_source_record()
        queue_id = self._insert_queue_row(source_record_id)
        review = self._new_model_review(queue_id)
        review["canonical_slug"] = "moonshotai/kimi-k2-turbo-3-5"
        review["display_name"] = "Kimi K2 Turbo 3.5"
        review["aliases"] = ["kimi-k2-turbo-3-5", "moonshotai/kimi-k2-turbo-3-5"]

        with patch.object(resolver, "utcnow", return_value=FROZEN_NOW):
            summary = resolver.accept_new_model_batch(self.conn, [review], dry_run=False)

        created_model_id = summary["items"][0]["model_id"]
        self.assertEqual(
            self.conn.execute(
                "SELECT display_name FROM model WHERE id = ?",
                (created_model_id,),
            ).fetchone()[0],
            "Kimi K2 Turbo 3.5",
        )
    def test_alias_collision_refuses_new_model_without_mutating_review_state(self) -> None:
        source_record_id = self._insert_source_record()
        queue_id = self._insert_queue_row(source_record_id)
        self.conn.execute(
            """
            INSERT INTO model_alias (
                id, source_id, alias_string, alias_normalized, alias_kind, model_id,
                resolution_method, confidence, source_snapshot_id, first_seen_at, last_seen_at
            ) VALUES (
                301, 'artificialanalysis', 'kimi-k2-turbo', 'kimi-k2-turbo',
                'api_model_id', 1, 'manual_review', 1.0, 201,
                '2026-07-02T19:00:00+00:00', '2026-07-02T19:00:00+00:00'
            )
            """
        )
        review = self._new_model_review(queue_id)
        before = self._state_snapshot()

        with self.assertRaises(ValueError):
            resolver.accept_new_model_batch(self.conn, [review], dry_run=False)

        self.assertEqual(self._state_snapshot(), before)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM model WHERE id <> 1").fetchone()[0],
            0,
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT model_id FROM model_alias WHERE id = 301"
            ).fetchone()[0],
            1,
        )
        self.assertIsNone(
            self.conn.execute(
                "SELECT model_alias_id FROM source_model_record WHERE id = ?",
                (source_record_id,),
            ).fetchone()[0]
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT candidate_model_id, status, resolved_at FROM entity_resolution_queue WHERE id = ?",
                (queue_id,),
            ).fetchone(),
            (None, "pending", None),
        )
        self.assertEqual(self._audit_rows(), [])

    def test_invalid_reviews_missing_required_canonical_developer_or_aliases_refuse_without_mutation(self) -> None:
        for name, invalid_fields in [
            ("missing canonical_slug", {"canonical_slug": None}),
            ("missing developer_id", {"developer_id": None}),
            ("missing aliases", {"aliases": None}),
            ("empty aliases", {"aliases": []}),
        ]:
            with self.subTest(name=name):
                conn = self._new_isolated_connection()
                source_record_id = self._insert_source_record(conn=conn)
                queue_id = self._insert_queue_row(source_record_id, conn=conn)
                review = self._new_model_review(queue_id)
                for key, value in invalid_fields.items():
                    if value is None:
                        review.pop(key)
                    else:
                        review[key] = value
                before = self._state_snapshot(conn=conn)

                with self.assertRaises(ValueError):
                    resolver.accept_new_model_batch(conn, [review], dry_run=False)

                self.assertEqual(self._state_snapshot(conn=conn), before)
                conn.close()

    def test_existing_canonical_slug_refuses_new_model_path_and_points_to_existing_accept_batch(self) -> None:
        source_record_id = self._insert_source_record()
        queue_id = self._insert_queue_row(source_record_id)
        review = self._new_model_review(queue_id)
        review["canonical_slug"] = "anthropic/claude-sonnet-4.5"
        review["developer_id"] = "anthropic"
        before = self._state_snapshot()

        with self.assertRaisesRegex(ValueError, "accept-batch"):
            resolver.accept_new_model_batch(self.conn, [review], dry_run=False)

        self.assertEqual(self._state_snapshot(), before)

    def test_accept_new_model_batch_dry_run_cli_prints_json_without_mutation(self) -> None:
        source_record_id = self._insert_source_record()
        queue_id = self._insert_queue_row(source_record_id)
        review = self._new_model_review(queue_id)
        before = self._state_snapshot()
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "new-model-review.json"
            path.write_text(json.dumps([review]), encoding="utf-8")
            with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
                with patch.object(resolver, "utcnow", return_value=FROZEN_NOW):
                    with redirect_stdout(stdout):
                        exit_code = resolver.main(["accept-new-model-batch", "--dry-run", str(path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["created"], 1)
        self.assertIs(payload["dry_run"], True)
        self.assertEqual(payload["items"][0]["queue_id"], queue_id)
        self.assertEqual(payload["items"][0]["canonical_slug"], "moonshotai/kimi-k2-turbo")
        self.assertEqual(payload["items"][0]["developer_id"], "moonshotai")
        self.assertEqual(self._state_snapshot(), before)

    def _new_isolated_connection(self) -> sqlite3.Connection:
        script = "\n".join(self.conn.iterdump())
        conn = sqlite3.connect(":memory:")
        conn.executescript(script)
        return conn

    def _insert_source_record(self, *, conn: sqlite3.Connection | None = None) -> int:
        target = self.conn if conn is None else conn
        target.execute(
            """
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES (201, 'artificialanalysis', 'memory://artificialanalysis/models',
                    '2026-07-03T08:55:00+00:00', 'sha256-fixture-201', 'test', NULL)
            """
        )
        cursor = target.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json, model_alias_id)
            VALUES (101, 201, 'kimi-k2-turbo', 'Kimi K2 Turbo', 'Moonshot AI', ?, ?, NULL)
            """,
            (
                json.dumps({"id": "kimi-k2-turbo", "name": "Kimi K2 Turbo"}, sort_keys=True),
                json.dumps({"model_creator_slug": "moonshotai"}, sort_keys=True),
            ),
        )
        return int(cursor.lastrowid)

    def _insert_queue_row(self, source_record_id: int, *, conn: sqlite3.Connection | None = None) -> int:
        target = self.conn if conn is None else conn
        features = {
            "model_creator_slug": "moonshotai",
            "model_name": "Kimi K2 Turbo",
            "provider_scoped_candidates": [
                "moonshotai-kimi-k2-turbo-unreviewed",
                "moonshotai-kimi-k2-turbo-router-only",
            ],
        }
        cursor = target.execute(
            """
            INSERT INTO entity_resolution_queue
                (source_record_id, candidate_model_id, reason, features_json, status, created_at, resolved_at)
            VALUES (?, NULL, 'needs new canonical model', ?, 'pending', '2026-07-03T08:56:00+00:00', NULL)
            """,
            (source_record_id, json.dumps(features, sort_keys=True)),
        )
        return int(cursor.lastrowid)

    def _new_model_review(self, queue_id: int) -> dict[str, object]:
        return {
            "queue_id": queue_id,
            "canonical_slug": "moonshotai/kimi-k2-turbo",
            "developer_id": "moonshotai",
            "aliases": ["kimi-k2-turbo", "moonshotai/kimi-k2-turbo"],
        }

    def _state_snapshot(self, *, conn: sqlite3.Connection | None = None) -> dict[str, list[tuple[object, ...]]]:
        target = self.conn if conn is None else conn
        return {
            "model": target.execute(
                """
                SELECT id, canonical_slug, developer_id, canonical_confidence, created_at, updated_at
                FROM model
                ORDER BY id
                """
            ).fetchall(),
            "model_alias": target.execute(
                """
                SELECT id, source_id, alias_string, alias_normalized, alias_kind, model_id,
                       resolution_method, confidence, source_snapshot_id, first_seen_at, last_seen_at
                FROM model_alias
                ORDER BY id
                """
            ).fetchall(),
            "source_model_record": target.execute(
                """
                SELECT id, source_snapshot_id, source_model_id, model_alias_id
                FROM source_model_record
                ORDER BY id
                """
            ).fetchall(),
            "entity_resolution_queue": target.execute(
                """
                SELECT id, source_record_id, candidate_model_id, status, resolved_at, features_json
                FROM entity_resolution_queue
                ORDER BY id
                """
            ).fetchall(),
            "entity_resolution_audit": self._audit_rows(conn=target),
        }

    def _audit_rows(self, *, conn: sqlite3.Connection | None = None) -> list[tuple[object, ...]]:
        target = self.conn if conn is None else conn
        exists = target.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'entity_resolution_audit'
            """
        ).fetchone()
        if exists is None:
            return []
        return target.execute(
            """
            SELECT action, queue_id, source_record_id, candidate_model_id, details_json
            FROM entity_resolution_audit
            ORDER BY id
            """
        ).fetchall()


class _ExistingConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
