"""End-to-end M1 pipeline: ingest -> spine -> bridge -> promote facts.

Usage:
    python -m store.pipeline              # full rebuild from scratch
    python -m store.pipeline --no-fetch   # skip network fetch, reuse last snapshots

Ordering matters:
  1. ingest source parsers (models_dev, openrouter, epoch) -> source_model_record
  2. build_spine            -> canonical `model` rows + models.dev aliases
  3. bridge_openrouter      -> OpenRouter + HF aliases onto the spine
  4. promote_prices         -> price_component (needs spine aliases for link_model)
  5. promote_benchmarks     -> benchmark + benchmark_result (needs spine aliases)
"""
from __future__ import annotations

import argparse

from ingest.base import connect
from ingest.run import build_registry, run_source
from store.spine import build_spine, bridge_openrouter_aliases
from store.prices import promote_prices
from store.benchmarks import promote_benchmarks
from store.arena import promote_arena
from store.capabilities import promote_capabilities
from store.announcement import capture_announcement, SONNET5_EVIDENCE

M1_SOURCES = ("models_dev", "openrouter", "epoch", "lmarena")


def run_pipeline(fetch: bool = True) -> dict:
    summary: dict = {}
    with connect() as conn:
        if fetch:
            registry, unavailable = build_registry()
            ingest_results = []
            for src in M1_SOURCES:
                cls = registry.get(src)
                if cls is None:
                    ingest_results.append(f"{src}: unavailable ({unavailable.get(src, '?')})")
                    continue
                ingest_results.append(run_source(src, cls, conn))
            summary["ingest"] = ingest_results

        summary["spine"] = build_spine(conn)
        summary["announcement"] = capture_announcement(conn, SONNET5_EVIDENCE)
        summary["bridge"] = bridge_openrouter_aliases(conn)
        summary["prices"] = promote_prices(conn)
        summary["capabilities"] = promote_capabilities(conn)
        summary["benchmarks"] = promote_benchmarks(conn)
        summary["arena"] = promote_arena(conn)
        conn.commit()
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the modeldb M1 pipeline.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip network ingest, reuse existing snapshots")
    args = ap.parse_args(argv)
    result = run_pipeline(fetch=not args.no_fetch)
    for stage, value in result.items():
        print(f"{stage}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
