"""SWE-bench leaderboard source parser stub."""
from __future__ import annotations

from collections.abc import Iterator
from urllib.request import urlopen

from ingest.base import SourceModelRecord, SourceParser


URL = "https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json"


class SWEBench(SourceParser):
    """Parser stub for SWE-bench leaderboard JSON."""

    source_id = "swebench"
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        with urlopen(URL) as response:
            raw = response.read()
            headers = response.headers
            meta = {
                "etag": headers.get("ETag"),
                "last_modified": headers.get("Last-Modified"),
            }
            return response.geturl(), raw, meta

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        """Extract leaderboards.json entries per leaderboard (Full, Lite, Verified,
        Multimodal): name, folder, resolved/% resolved, date, org/model flags, and cost.
        Emit benchmark_result records with self_reported=0.
        """
        # TODO(M2): Parse each leaderboard family into benchmark_result source rows.
        yield from ()
