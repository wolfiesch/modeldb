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


class AcceptOrganizationBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE organization (
                id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                country TEXT,
                aliases_json TEXT
            );

            INSERT INTO organization (id, display_name, country, aliases_json)
            VALUES ('anthropic', 'Anthropic', 'US', '["claude"]');
            """
        )

    def test_valid_dry_run_reports_created_items_without_mutating_organizations(self) -> None:
        reviews = [
            {
                "id": "xai",
                "display_name": "xAI",
                "country": "US",
                "aliases": ["x.ai", "grok creator"],
            },
            {
                "id": "mistral-ai",
                "display_name": "Mistral AI",
            },
        ]
        before = self._organization_rows()

        summary = resolver.accept_organization_batch(self.conn, reviews, dry_run=True)

        self.assertEqual(summary["created"], 2)
        self.assertIs(summary["dry_run"], True)
        self.assertEqual(
            [(item["id"], item["display_name"], item["country"], item["aliases"]) for item in summary["items"]],
            [
                ("xai", "xAI", "US", ["x.ai", "grok creator"]),
                ("mistral-ai", "Mistral AI", None, []),
            ],
        )
        self.assertEqual(self._organization_rows(), before)

    def test_real_run_creates_organization_rows_with_optional_fields_and_deterministic_alias_json(self) -> None:
        reviews = [
            {
                "id": "xai",
                "display_name": "xAI",
                "country": "US",
                "aliases": ["x.ai", "grok creator"],
            },
            {
                "id": "mistral-ai",
                "display_name": "Mistral AI",
            },
        ]

        summary = resolver.accept_organization_batch(self.conn, reviews, dry_run=False)

        self.assertEqual(summary["created"], 2)
        self.assertIs(summary["dry_run"], False)
        rows_by_id = {row[0]: row[1:] for row in self._organization_rows()}
        self.assertEqual(set(rows_by_id), {"anthropic", "mistral-ai", "xai"})
        self.assertEqual(rows_by_id["anthropic"], ("Anthropic", "US", '["claude"]'))
        self.assertEqual(rows_by_id["mistral-ai"][:2], ("Mistral AI", None))
        self.assertEqual(
            rows_by_id["xai"],
            ("xAI", "US", json.dumps(["x.ai", "grok creator"], separators=(",", ":"), sort_keys=True)),
        )

    def test_existing_organization_id_refuses_entire_batch_without_mutation(self) -> None:
        before = self._organization_rows()

        with self.assertRaises(ValueError):
            resolver.accept_organization_batch(
                self.conn,
                [
                    {"id": "xai", "display_name": "xAI"},
                    {"id": "anthropic", "display_name": "Anthropic Labs"},
                ],
                dry_run=False,
            )

        self.assertEqual(self._organization_rows(), before)

    def test_invalid_required_fields_and_alias_type_refuse_without_mutation(self) -> None:
        invalid_reviews = [
            ("missing id", {"display_name": "xAI"}),
            ("empty id", {"id": "   ", "display_name": "xAI"}),
            ("missing display_name", {"id": "xai"}),
            ("empty display_name", {"id": "xai", "display_name": "   "}),
            ("non-list aliases", {"id": "xai", "display_name": "xAI", "aliases": "x.ai"}),
        ]

        for name, invalid_review in invalid_reviews:
            with self.subTest(name=name):
                conn = self._new_isolated_connection()
                self.addCleanup(conn.close)
                before = self._organization_rows(conn=conn)

                with self.assertRaises(ValueError):
                    resolver.accept_organization_batch(
                        conn,
                        [
                            {"id": "mistral-ai", "display_name": "Mistral AI"},
                            invalid_review,
                        ],
                        dry_run=False,
                    )

                self.assertEqual(self._organization_rows(conn=conn), before)

    def test_accept_organization_batch_dry_run_cli_prints_json_without_mutation(self) -> None:
        reviews = [
            {
                "id": "xai",
                "display_name": "xAI",
                "country": "US",
                "aliases": ["x.ai", "grok creator"],
            }
        ]
        before = self._organization_rows()
        stdout = io.StringIO()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "organization-review.json"
            path.write_text(json.dumps(reviews), encoding="utf-8")
            with patch.object(resolver, "connect", return_value=_ExistingConnection(self.conn)):
                with redirect_stdout(stdout):
                    exit_code = resolver.main(["accept-organization-batch", "--dry-run", str(path)])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["created"], 1)
        self.assertIs(payload["dry_run"], True)
        self.assertEqual(payload["items"][0]["id"], "xai")
        self.assertEqual(payload["items"][0]["display_name"], "xAI")
        self.assertEqual(payload["items"][0]["country"], "US")
        self.assertEqual(payload["items"][0]["aliases"], ["x.ai", "grok creator"])
        self.assertEqual(self._organization_rows(), before)

    def _new_isolated_connection(self) -> sqlite3.Connection:
        script = "\n".join(self.conn.iterdump())
        conn = sqlite3.connect(":memory:")
        conn.executescript(script)
        return conn

    def _organization_rows(self, *, conn: sqlite3.Connection | None = None) -> list[tuple[object, ...]]:
        target = self.conn if conn is None else conn
        return target.execute(
            """
            SELECT id, display_name, country, aliases_json
            FROM organization
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
