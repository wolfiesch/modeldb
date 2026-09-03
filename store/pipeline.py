"""End-to-end M1 pipeline: ingest -> spine -> bridge -> promote facts.

Usage:
    python -m store.pipeline              # full rebuild from scratch
    python -m store.pipeline --no-fetch   # skip network fetch, reuse last snapshots

Ordering matters:
  1. ingest source parsers (models_dev, openrouter, epoch) -> source_model_record
  2. build_spine            -> canonical `model` rows + models.dev aliases
  3. launch_registry        -> curated launch-window rows no catalog lists yet
  4. bridge_openrouter      -> OpenRouter + HF aliases onto the spine
  5. promote_prices         -> price_component (needs spine aliases for link_model)
  6. promote_benchmarks     -> benchmark + benchmark_result (needs spine aliases)
"""
from __future__ import annotations

import argparse

from ingest.base import connect
from ingest.run import build_registry, run_source
from store.spine import build_spine, bridge_openrouter_aliases
from store.surfaces import promote_surfaces
from store.artifacts import fetch_huggingface_records, promote_artifacts
from store.openrouter_endpoints import promote_openrouter_endpoints
from store.prices import promote_prices
from store.benchmarks import promote_benchmarks
from store.external_benchmarks import promote_external_benchmarks
from store.open_llm_lb import promote_open_llm_lb
from store.mteb import promote_mteb
from store.artificial_analysis import promote_artificial_analysis
from store.omp_speedtest import promote_omp_speedtest
from store.vllm import promote_vllm
from store.deepswe import promote_deepswe
from store.frontierswe import promote_frontierswe
from store.arena import promote_arena
from store.capabilities import promote_capabilities
from store.launch_registry import promote_launch_registry
from store.launch_benchmarks import promote_launch_benchmarks

M1_SOURCES = (
    "models_dev",
    "openrouter",
    "epoch",
    "lmarena",
    "swebench",
    "aider",
    "deepswe",
    "frontierswe",
    "openvlm",
    "bigcodebench",
    "vllm",
    "open_llm_lb",
    "artificialanalysis",
)


def run_pipeline(
    fetch: bool = True,
    *,
    enrich_network: bool = False,
    huggingface_limit: int = 100,
    openrouter_endpoint_limit: int = 150,
) -> dict:
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
        summary["launch_registry"] = promote_launch_registry(conn)
        summary["bridge"] = bridge_openrouter_aliases(conn)
        summary["surfaces"] = promote_surfaces(conn)
        summary["artifacts"] = promote_artifacts(conn)
        if enrich_network:
            summary["huggingface_fetch"] = fetch_huggingface_records(conn, limit=huggingface_limit)
            summary["artifacts"] = promote_artifacts(conn)
            summary["openrouter_endpoints"] = promote_openrouter_endpoints(
                conn,
                limit=openrouter_endpoint_limit,
            )
        summary["prices"] = promote_prices(conn)
        summary["capabilities"] = promote_capabilities(conn)
        summary["benchmarks"] = promote_benchmarks(conn)
        summary["arena"] = promote_arena(conn)
        summary["external_benchmarks"] = promote_external_benchmarks(conn)
        summary["open_llm_lb"] = promote_open_llm_lb(conn)
        summary["mteb"] = promote_mteb(conn)
        summary["deepswe"] = promote_deepswe(conn)
        summary["frontierswe"] = promote_frontierswe(conn)
        summary["artificial_analysis"] = promote_artificial_analysis(conn)
        summary["omp_speedtest"] = promote_omp_speedtest(conn)
        summary["vllm"] = promote_vllm(conn)
        summary["launch_benchmarks"] = promote_launch_benchmarks(conn)
        conn.commit()
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the modeldb M1 pipeline.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="skip core source ingest, reuse existing snapshots")
    ap.add_argument("--enrich-network", action="store_true",
                    help="run capped network enrichment for Hugging Face metadata and OpenRouter endpoints")
    ap.add_argument("--huggingface-limit", type=int, default=100,
                    help="maximum known Hugging Face repos to enrich when --enrich-network is set")
    ap.add_argument("--openrouter-endpoint-limit", type=int, default=150,
                    help="maximum known OpenRouter models to enrich when --enrich-network is set")
    args = ap.parse_args(argv)
    result = run_pipeline(
        fetch=not args.no_fetch,
        enrich_network=args.enrich_network,
        huggingface_limit=args.huggingface_limit,
        openrouter_endpoint_limit=args.openrouter_endpoint_limit,
    )
    for stage, value in result.items():
        print(f"{stage}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
