from __future__ import annotations

import json

import os
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store.spine import link_model


class ArtificialAnalysisLinkModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE model (
                id INTEGER PRIMARY KEY,
                canonical_slug TEXT NOT NULL,
                developer_id TEXT
            );
            CREATE TABLE model_alias (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                alias_string TEXT NOT NULL,
                alias_normalized TEXT NOT NULL,
                alias_kind TEXT NOT NULL,
                model_id INTEGER,
                confidence REAL NOT NULL
            );
            INSERT INTO model (id, canonical_slug, developer_id)
            VALUES
                (1, 'anthropic/claude-sonnet-4', 'anthropic'),
                (2, 'alibaba/qwen3.5-122b-a10b', 'alibaba');
            INSERT INTO model_alias
                (source_id, alias_string, alias_normalized, alias_kind, model_id, confidence)
            VALUES
                ('models_dev', 'anthropic/claude-sonnet-4', 'anthropic-claude-sonnet-4', 'api_model_id', 1, 1.0),
                ('models_dev', 'claude-sonnet-4', 'claude-sonnet-4', 'bare_name', 1, 1.0),
                ('models_dev', 'claude-4-sonnet', 'claude-4-sonnet', 'bare_display_name', 1, 0.5),
                ('models_dev', 'alibaba/qwen3.5-122b-a10b', 'alibaba-qwen3-5-122b-a10b', 'api_model_id', 2, 1.0);
            """
        )

    def test_provider_scoped_artificial_analysis_slug_links_to_canonical_alias(self) -> None:
        parsed_fields = {
            "model_creator_slug": "anthropic",
            "slug": "claude-4-sonnet",
            "name": "Claude 4 Sonnet (Non-reasoning)",
        }

        model_id = link_model(
            self.conn,
            source_id="artificialanalysis",
            source_model_id="claude-4-sonnet",
            parsed_fields=parsed_fields,
        )

        canonical_slug = self.conn.execute(
            "SELECT canonical_slug FROM model WHERE id = ?", (model_id,)
        ).fetchone()[0]
        self.assertEqual(canonical_slug, "anthropic/claude-sonnet-4")

    def test_non_reasoning_artificial_analysis_slug_links_to_canonical_alias(self) -> None:
        parsed_fields = {
            "model_creator_slug": "alibaba",
            "slug": "qwen3-5-122b-a10b-non-reasoning",
            "name": "Qwen3.5 122B A10B Non-Reasoning",
        }

        model_id = link_model(
            self.conn,
            source_id="artificialanalysis",
            source_model_id="qwen3-5-122b-a10b-non-reasoning",
            parsed_fields=parsed_fields,
        )

        self.assertIsNotNone(model_id)

        canonical_slug = self.conn.execute(
            "SELECT canonical_slug FROM model WHERE id = ?", (model_id,)
        ).fetchone()[0]
        self.assertEqual(canonical_slug, "alibaba/qwen3.5-122b-a10b")

    def test_wrong_provider_does_not_link_through_bare_artificial_analysis_name(self) -> None:
        parsed_fields = {
            "model_creator_slug": "openai",
            "slug": "claude-4-sonnet",
            "name": "Claude 4 Sonnet (Non-reasoning)",
        }

        model_id = link_model(
            self.conn,
            source_id="artificialanalysis",
            source_model_id="claude-4-sonnet",
            parsed_fields=parsed_fields,
        )

        self.assertIsNone(model_id)



class ArtificialAnalysisPromotionQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE source_snapshot (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                parser_version TEXT NOT NULL,
                raw_path TEXT
            );
            CREATE TABLE source_model_record (
                id INTEGER PRIMARY KEY,
                source_snapshot_id INTEGER NOT NULL,
                source_model_id TEXT NOT NULL,
                display_name TEXT,
                provider_name TEXT,
                raw_record_json TEXT NOT NULL,
                parsed_fields_json TEXT,
                model_alias_id INTEGER
            );
            CREATE TABLE model (
                id INTEGER PRIMARY KEY,
                canonical_slug TEXT NOT NULL,
                developer_id TEXT
            );
            CREATE TABLE model_alias (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                alias_string TEXT NOT NULL,
                alias_normalized TEXT NOT NULL,
                alias_kind TEXT NOT NULL,
                model_id INTEGER,
                confidence REAL NOT NULL
            );
            CREATE TABLE benchmark (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                metric_default TEXT,
                higher_is_better INTEGER,
                source_url TEXT
            );
            CREATE TABLE benchmark_result (
                id INTEGER PRIMARY KEY,
                model_id INTEGER,
                provider_surface_id INTEGER,
                benchmark_id TEXT,
                score REAL,
                metric TEXT,
                rank INTEGER,
                ci TEXT,
                votes INTEGER,
                eval_condition_json TEXT,
                self_reported INTEGER,
                measured_at TEXT,
                source_snapshot_id INTEGER,
                raw_record_json TEXT
            );
            CREATE TABLE model_capability (
                model_id INTEGER NOT NULL,
                capability TEXT NOT NULL,
                value TEXT NOT NULL,
                source_snapshot_id INTEGER,
                confidence REAL NOT NULL
            );
            CREATE TABLE price_component (
                id INTEGER PRIMARY KEY,
                model_id INTEGER,
                provider_surface_id INTEGER,
                source_id TEXT,
                component TEXT,
                unit TEXT,
                currency TEXT,
                amount REAL,
                normalized_usd_per_1m_tokens REAL,
                tier_condition_json TEXT,
                valid_from TEXT,
                valid_to TEXT,
                source_snapshot_id INTEGER
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
            INSERT INTO source_snapshot
                (id, source_id, url, fetched_at, content_hash, parser_version, raw_path)
            VALUES
                (1, 'artificialanalysis', 'https://artificialanalysis.ai/api/v2/data/llms/models',
                 '2026-07-02T19:00:00+00:00', 'snapshot-hash', '0.2.0', NULL);
            INSERT INTO model (id, canonical_slug, developer_id)
            VALUES (1, 'anthropic/claude-sonnet-4', 'anthropic');
            INSERT INTO model_alias
                (source_id, alias_string, alias_normalized, alias_kind, model_id, confidence)
            VALUES
                ('models_dev', 'anthropic/claude-sonnet-4', 'anthropic-claude-sonnet-4',
                 'api_model_id', 1, 1.0);
            """
        )

    def test_unlinked_artificial_analysis_records_queue_provider_scoped_candidates_once(self) -> None:
        from store.artificial_analysis import promote_artificial_analysis

        parsed_fields = {
            "id": "aa-qwen3-5-omni-plus",
            "model_creator_slug": "alibaba",
            "slug": "qwen3-5-omni-plus",
            "name": "Qwen3.5 Omni Plus",
            "evaluations": {"artificial_analysis_intelligence_index": 58.4},
        }
        self.conn.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            """,
            (
                7,
                "aa-qwen3-5-omni-plus",
                "Qwen3.5 Omni Plus",
                "Alibaba",
                json.dumps({"slug": "qwen3-5-omni-plus"}),
                json.dumps(parsed_fields),
            ),
        )

        promote_artificial_analysis(self.conn)

        rows = self.conn.execute(
            """
            SELECT source_record_id, status, features_json
            FROM entity_resolution_queue
            WHERE source_record_id = ? AND status = 'pending'
            """,
            (7,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 7)
        self.assertEqual(rows[0][1], "pending")

        features = json.loads(rows[0][2])
        candidates = features.get("provider_scoped_candidates")
        self.assertIsInstance(candidates, list)
        self.assertIn("alibaba-qwen3-5-omni-plus", candidates)
        self.assertNotIn("qwen3-5-omni-plus", candidates)

        promote_artificial_analysis(self.conn)

        pending_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM entity_resolution_queue
            WHERE source_record_id = ? AND status = 'pending'
            """,
            (7,),
        ).fetchone()[0]
        self.assertEqual(pending_count, 1)

    def test_linked_artificial_analysis_record_clears_pending_null_candidate_queue(self) -> None:
        from store.artificial_analysis import promote_artificial_analysis

        parsed_fields = {
            "id": "aa-claude-4-sonnet-preview",
            "model_creator_slug": "anthropic",
            "slug": "claude-4-sonnet-preview",
            "name": "Claude 4 Sonnet Preview",
            "evaluations": {"artificial_analysis_intelligence_index": 72.0},
        }
        self.conn.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            """,
            (
                8,
                "aa-claude-4-sonnet-preview",
                "Claude 4 Sonnet Preview",
                "Anthropic",
                json.dumps({"slug": "claude-4-sonnet-preview"}),
                json.dumps(parsed_fields),
            ),
        )
        self.conn.execute(
            """
            INSERT INTO model_alias
                (source_id, alias_string, alias_normalized, alias_kind, model_id, confidence)
            VALUES
                ('models_dev', 'anthropic/claude-4-sonnet-preview', 'anthropic-claude-4-sonnet-preview',
                 'api_model_id', 1, 1.0)
            """
        )
        self.conn.execute(
            """
            INSERT INTO entity_resolution_queue
                (source_record_id, candidate_model_id, reason, features_json, status, created_at)
            VALUES
                (8, NULL, 'unresolved artificialanalysis provider-scoped aliases',
                 '{"provider_scoped_candidates":["anthropic-claude-4-sonnet-preview"]}',
                 'pending', '2026-07-02T19:00:00+00:00')
            """
        )

        summary = promote_artificial_analysis(self.conn)

        self.assertEqual(summary["queue_cleared"], 1)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM entity_resolution_queue WHERE source_record_id = 8 AND status = 'pending'"
            ).fetchone()[0],
            0,
        )

    def test_fractional_benchmark_scores_are_promoted_as_percentage_points(self) -> None:
        from store.artificial_analysis import promote_artificial_analysis

        parsed_fields = {
            "id": "aa-claude-sonnet-4",
            "model_creator_slug": "anthropic",
            "slug": "claude-sonnet-4",
            "name": "Claude Sonnet 4",
            "evaluations": {
                "mmlu_pro": 0.898,
                "artificial_analysis_intelligence_index": 61.0,
            },
        }
        self.conn.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            """,
            (
                10,
                "aa-claude-sonnet-4",
                "Claude Sonnet 4",
                "Anthropic",
                json.dumps({"slug": "claude-sonnet-4"}),
                json.dumps(parsed_fields),
            ),
        )

        promote_artificial_analysis(self.conn)

        rows = self.conn.execute(
            """
            SELECT br.benchmark_id, br.score, br.metric, b.metric_default
            FROM benchmark_result br
            JOIN benchmark b ON b.id = br.benchmark_id
            ORDER BY br.benchmark_id
            """
        ).fetchall()
        self.assertEqual(
            rows,
            [
                ("artificial_analysis_intelligence_index", 61.0, "index", "index"),
                ("mmlu_pro", 89.8, "percent", "percent"),
            ],
        )

    def test_linked_variant_prices_keep_source_variant_as_tier_condition(self) -> None:
        from store.artificial_analysis import promote_artificial_analysis

        parsed_fields = {
            "id": "aa-claude-sonnet-4-high",
            "model_creator_slug": "anthropic",
            "model_version": "anthropic/claude-sonnet-4 (high)",
            "slug": "claude-sonnet-4-high",
            "name": "Claude Sonnet 4 (high)",
            "price_1m_input_tokens": 3.0,
            "price_1m_output_tokens": 15.0,
        }
        self.conn.execute(
            """
            INSERT INTO source_model_record
                (id, source_snapshot_id, source_model_id, display_name, provider_name,
                 raw_record_json, parsed_fields_json)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            """,
            (
                9,
                "aa-claude-sonnet-4-high",
                "Claude Sonnet 4 (high)",
                "Anthropic",
                json.dumps({"slug": "claude-sonnet-4-high"}),
                json.dumps(parsed_fields),
            ),
        )

        promote_artificial_analysis(self.conn)

        tier_conditions = {
            row[0]
            for row in self.conn.execute(
                "SELECT tier_condition_json FROM price_component WHERE model_id = 1"
            )
        }
        self.assertEqual(
            tier_conditions,
            {'{"model_version": "anthropic/claude-sonnet-4 (high)", "slug": "claude-sonnet-4-high"}'},
        )



class ArtificialAnalysisFetchCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.repo_root = Path(self.tmpdir.name)
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.conn.executescript(
            """
            CREATE TABLE source_snapshot (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                content_hash TEXT,
                etag TEXT,
                last_modified TEXT,
                parser_version TEXT,
                raw_path TEXT NOT NULL
            );
            """
        )
        self.now = datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc)

    def _write_snapshot(self, *, fetched_at: datetime, raw: bytes) -> None:
        raw_path = Path("data/raw/artificialanalysis/cached.raw")
        absolute_raw_path = self.repo_root / raw_path
        absolute_raw_path.parent.mkdir(parents=True, exist_ok=True)
        absolute_raw_path.write_bytes(raw)
        self.conn.execute(
            """
            INSERT INTO source_snapshot
                (source_id, url, fetched_at, content_hash, etag, last_modified, parser_version, raw_path)
            VALUES
                ('artificialanalysis', 'https://artificialanalysis.ai/api/v2/data/llms/models', ?,
                 'cached-hash', 'cached-etag', 'cached-last-modified', '0.2.0', ?)
            """,
            (fetched_at.isoformat(), str(raw_path)),
        )
        self.conn.commit()

    def test_fetch_with_cache_reuses_fresh_snapshot_without_network(self) -> None:
        from ingest.sources.artificialanalysis import fetch_with_cache

        cached_raw = b'{"data":[{"slug":"cached"}]}'
        self._write_snapshot(fetched_at=self.now - timedelta(hours=1), raw=cached_raw)

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("fresh Artificial Analysis cache should avoid a network request")

        url, raw, meta = fetch_with_cache(
            self.conn,
            now=self.now,
            repo_root=self.repo_root,
            urlopen_fn=fail_if_called,
        )

        self.assertEqual(url, "https://artificialanalysis.ai/api/v2/data/llms/models")
        self.assertEqual(raw, cached_raw)
        self.assertEqual(meta.get("etag"), "cached-etag")
        self.assertEqual(meta.get("last_modified"), "cached-last-modified")

    def test_fetch_with_cache_fetches_when_cached_snapshot_is_stale(self) -> None:
        from ingest.sources.artificialanalysis import PRIMARY_API_KEY_ENV, fetch_with_cache

        self._write_snapshot(fetched_at=self.now - timedelta(days=4), raw=b'{"data":[{"slug":"stale"}]}')
        network = _FakeUrlopen(b'{"data":[{"slug":"fresh"}]}')

        with _patched_env(**{PRIMARY_API_KEY_ENV: "placeholder-token"}):
            url, raw, meta = fetch_with_cache(
                self.conn,
                now=self.now,
                repo_root=self.repo_root,
                urlopen_fn=network,
            )

        self.assertEqual(network.calls, 1)
        self.assertEqual(network.request_urls, ["https://artificialanalysis.ai/api/v2/data/llms/models"])
        self.assertEqual(url, "https://artificialanalysis.ai/api/v2/data/llms/models")
        self.assertEqual(raw, b'{"data":[{"slug":"fresh"}]}')
        self.assertEqual(meta.get("etag"), "fresh-etag")
        self.assertEqual(meta.get("last_modified"), "fresh-last-modified")


class _FakeResponse:
    headers = {"ETag": "fresh-etag", "Last-Modified": "fresh-last-modified"}

    def __init__(self, url: str, raw: bytes) -> None:
        self._url = url
        self._raw = raw

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc_info) -> None:
        return None

    def read(self) -> bytes:
        return self._raw

    def geturl(self) -> str:
        return self._url


class _FakeUrlopen:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.calls = 0
        self.request_urls: list[str] = []

    def __call__(self, request):
        self.calls += 1
        self.request_urls.append(request.full_url)
        return _FakeResponse(request.full_url, self.raw)


@contextmanager
def _patched_env(**values: str):
    with patch.dict(os.environ, values, clear=False):
        yield


if __name__ == "__main__":
    unittest.main()
