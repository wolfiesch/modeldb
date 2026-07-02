from __future__ import annotations

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
