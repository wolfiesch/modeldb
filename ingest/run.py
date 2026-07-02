"""CLI driver for modeldb source parsers.

Usage:
    python -m ingest.run <source_id|all>

The driver is intentionally small: parsers own fetch/parse logic, while
``SourceParser.run`` in ``ingest.base`` owns snapshotting and record storage.
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import sqlite3
from dataclasses import dataclass
from typing import Iterable

from ingest.base import SourceParser, connect


@dataclass(frozen=True)
class ParserSpec:
    source_id: str
    module: str
    class_name: str | None = None


PARSER_SPECS: tuple[ParserSpec, ...] = (
    ParserSpec("models_dev", "ingest.sources.models_dev", "ModelsDevParser"),
    ParserSpec("openrouter", "ingest.sources.openrouter", "OpenRouterParser"),
    ParserSpec("epoch", "ingest.sources.epoch", "EpochParser"),
    ParserSpec("lmarena", "ingest.sources.lmarena", "LMArenaParser"),
    ParserSpec("litellm", "ingest.sources.litellm", "LiteLLMParser"),
    ParserSpec("llm_prices", "ingest.sources.llm_prices", "LLMPricesParser"),
    ParserSpec("artificialanalysis", "ingest.sources.artificialanalysis", "ArtificialAnalysisParser"),
    ParserSpec("huggingface", "ingest.sources.huggingface", "HuggingFaceParser"),
    ParserSpec("vllm", "ingest.sources.vllm", "VLLMParser"),
    ParserSpec("swebench", "ingest.sources.swebench", "SWEBenchParser"),
    ParserSpec("aider", "ingest.sources.aider", "AiderParser"),
    ParserSpec("deepswe", "ingest.sources.deepswe", "DeepSWEParser"),
    ParserSpec("livebench", "ingest.sources.livebench", "LiveBenchParser"),
    ParserSpec("open_llm_lb", "ingest.sources.open_llm_lb", "OpenLLMLBParser"),
    ParserSpec("mteb", "ingest.sources.mteb", "MTEBParser"),
    ParserSpec("anthropic_api", "ingest.sources.anthropic_api", "AnthropicAPIParser"),
    ParserSpec("openai_api", "ingest.sources.openai_api", "OpenAIAPIParser"),
    ParserSpec("gemini_api", "ingest.sources.gemini_api", "GeminiAPIParser"),
    ParserSpec("mistral_api", "ingest.sources.mistral_api", "MistralAPIParser"),
    ParserSpec("hf_model_card", "ingest.sources.hf_model_card", "HFModelCardParser"),
    ParserSpec("provider_blog", "ingest.sources.provider_blog", "ProviderBlogParser"),
    ParserSpec("lmarena_mirror", "ingest.sources.lmarena_mirror", "LMArenaMirrorParser"),
    ParserSpec("scale_seal", "ingest.sources.scale_seal", "ScaleSEALParser"),
)

# Live MTEB results are official HF parquet shards. Keep the parser discoverable
# for explicit aggregate JSON/CSV imports, but do not include it in the default
# stdlib-only `all` run.
EXCLUDE_FROM_ALL = {"mteb"}


class ParserUnavailable(RuntimeError):
    """Raised when a parser module or class is not present yet."""


def _discover_parser_class(spec: ParserSpec) -> type[SourceParser]:
    module = importlib.import_module(spec.module)

    if spec.class_name:
        candidate = getattr(module, spec.class_name, None)
        if inspect.isclass(candidate) and issubclass(candidate, SourceParser):
            return candidate

    for _, candidate in inspect.getmembers(module, inspect.isclass):
        if candidate is SourceParser or not issubclass(candidate, SourceParser):
            continue
        if getattr(candidate, "source_id", None) == spec.source_id:
            return candidate

    expected = spec.class_name or f"SourceParser subclass with source_id={spec.source_id!r}"
    raise ParserUnavailable(f"{spec.module} has no {expected}")


def build_registry() -> tuple[dict[str, type[SourceParser]], dict[str, str]]:
    """Import available parser classes without failing on missing stub modules."""
    registry: dict[str, type[SourceParser]] = {}
    unavailable: dict[str, str] = {}

    for spec in PARSER_SPECS:
        try:
            registry[spec.source_id] = _discover_parser_class(spec)
        except (ImportError, AttributeError, ParserUnavailable) as exc:
            unavailable[spec.source_id] = str(exc)

    return registry, unavailable


def run_source(source_id: str, parser_cls: type[SourceParser], conn: sqlite3.Connection) -> str:
    parser = parser_cls()
    try:
        summary = parser.run(conn)
    except NotImplementedError as exc:
        detail = str(exc) or "parser fetch/parse is not implemented"
        return f"{source_id}: not yet implemented ({detail})"

    return (
        f"{summary['source']}: snapshot_id={summary['snapshot_id']} "
        f"records={summary['records']}"
    )


def iter_requested(source_id: str, registry: dict[str, type[SourceParser]]) -> Iterable[str]:
    if source_id == "all":
        return (
            spec.source_id
            for spec in PARSER_SPECS
            if spec.source_id in registry and spec.source_id not in EXCLUDE_FROM_ALL
        )
    return (source_id,)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one or all modeldb source parsers.")
    parser.add_argument("source", help="source_id to run, or 'all'")
    args = parser.parse_args(argv)

    registry, unavailable = build_registry()
    known_sources = {spec.source_id for spec in PARSER_SPECS}

    if args.source != "all" and args.source not in known_sources:
        parser.error(f"unknown source_id {args.source!r}; expected one of: {', '.join(sorted(known_sources))}, all")

    if args.source != "all" and args.source not in registry:
        reason = unavailable.get(args.source, "parser module is not available")
        print(f"{args.source}: unavailable ({reason})")
        return 1

    conn = connect()
    try:
        for source_id in iter_requested(args.source, registry):
            print(run_source(source_id, registry[source_id], conn))

        if args.source == "all":
            for source_id in sorted(set(unavailable) & known_sources):
                print(f"{source_id}: unavailable ({unavailable[source_id]})")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
