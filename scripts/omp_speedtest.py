#!/usr/bin/env python3
"""Small-token OMP model smoke and speed test wrapper."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from statistics import median
from typing import Any

DEFAULT_PROMPT = "Count from 1 to 30, one number per line, then stop."
VISIBLE_PROMPT = "Output 180 comma-separated integers starting at 1. No explanation."
DEFAULT_MAX_TOKENS = 48
DEFAULT_RUNS = 1
DEFAULT_TIMEOUT = 60
DEFAULT_JSONL = Path.home() / ".omp" / "agent" / "model-speedtests.jsonl"
TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)
PRESETS = {
    "frontier": [
        "openai-codex/gpt-5.5:medium",
        "google-antigravity/gemini-3.1-pro:low",
        "cursor/claude-opus-4-8-high",
        "google-antigravity/gemini-3.5-flash:medium",
        "openai-codex/gpt-5.3-codex-spark:low",
        "vibeproxy/kimi-k2.7-code-highspeed",
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small OMP benchmark for one or more configured models."
    )
    parser.add_argument("models", nargs="*", help="OMP model selectors, for example wafer/GLM-5.2")
    parser.add_argument("--preset", choices=sorted(PRESETS), help="Named model set to benchmark")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help=f"Requests per model, default {DEFAULT_RUNS}")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=DEFAULT_MAX_TOKENS,
        help=f"Output token cap per request, default {DEFAULT_MAX_TOKENS}",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Tiny benchmark prompt")
    parser.add_argument("--visible", action="store_true", help="Capture visible OMP stdout and compute local token/char metrics")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON")
    parser.add_argument("--interleave", action="store_true", help="Interleave runs across models (A, B, A, B)")
    parser.add_argument(
        "--jsonl",
        nargs="?",
        const=str(DEFAULT_JSONL),
        help=f"Append per-run records to JSONL, default path {DEFAULT_JSONL}",
    )
    parser.add_argument("--omp", default="omp", help="OMP executable path, default: omp")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help=f"Wall-clock timeout in seconds, default {DEFAULT_TIMEOUT}")
    return parser


def positive_int(value: int, name: str) -> None:
    if value < 1:
        raise SystemExit(f"{name} must be >= 1")



def selected_models(args: argparse.Namespace) -> list[str]:
    models = [*args.models]
    if args.preset:
        models = [*PRESETS[args.preset], *models]
    if not models:
        raise SystemExit("at least one model or --preset is required")
    return models


def local_token_count(text: str) -> int:
    return len(TOKEN_PATTERN.findall(text))


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * pct))
    return ordered[index]


def append_jsonl(path: str | None, records: list[dict[str, Any]]) -> None:
    if not path:
        return
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, sort_keys=True) + "\n")

def run_bench(args: argparse.Namespace) -> dict[str, Any]:
    positive_int(args.runs, "--runs")
    positive_int(args.max_tokens, "--max-tokens")
    positive_int(args.timeout, "--timeout")

    command = [
        args.omp,
        "bench",
        *selected_models(args),
        f"--runs={args.runs}",
        f"--max-tokens={args.max_tokens}",
        f"--prompt={args.prompt}",
        "--json",
    ]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, check=False, timeout=args.timeout)
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"omp bench timed out after {args.timeout} seconds") from exc
    if proc.returncode != 0:
        if proc.stdout:
            print(proc.stdout, file=sys.stderr, end="" if proc.stdout.endswith("\n") else "\n")
        if proc.stderr:
            print(proc.stderr, file=sys.stderr, end="" if proc.stderr.endswith("\n") else "\n")
        raise SystemExit(proc.returncode)

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(proc.stdout, file=sys.stderr)
        raise SystemExit(f"omp bench did not emit JSON: {exc}") from exc



def run_visible(args: argparse.Namespace) -> dict[str, Any]:
    positive_int(args.runs, "--runs")
    positive_int(args.timeout, "--timeout")
    if args.prompt == DEFAULT_PROMPT:
        args.prompt = VISIBLE_PROMPT
    models = selected_models(args)
    records: list[dict[str, Any]] = []
    if args.interleave:
        loop_vars = [(run_idx, model) for run_idx in range(1, args.runs + 1) for model in models]
    else:
        loop_vars = [(run_idx, model) for model in models for run_idx in range(1, args.runs + 1)]

    for run_index, model in loop_vars:
        command = [
            args.omp,
            "--model",
            model,
            "--no-tools",
            f"--max-time={args.timeout}",
            "-p",
            args.prompt,
        ]
        started = dt.datetime.now(dt.UTC)
        try:
            proc = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                timeout=args.timeout + 5,
            )
            duration_ms = max(1.0, (dt.datetime.now(dt.UTC) - started).total_seconds() * 1000)
        except subprocess.TimeoutExpired as exc:
            duration_ms = max(1.0, (dt.datetime.now(dt.UTC) - started).total_seconds() * 1000)
            records.append(
                {
                    "timestamp": started.isoformat(),
                    "mode": "visible",
                    "model": model,
                    "run": run_index,
                    "status": "timeout",
                    "durationMs": duration_ms,
                    "error": f"omp print timed out after {args.timeout} seconds",
                    "tokenizer": "regex-v1",
                }
            )
            continue

        output = proc.stdout.strip()
        visible_tokens = local_token_count(output)
        visible_chars = len(output)
        record = {
            "timestamp": started.isoformat(),
            "mode": "visible",
            "model": model,
            "run": run_index,
            "status": "ok" if proc.returncode == 0 else "error",
            "exitCode": proc.returncode,
            "durationMs": duration_ms,
            "visibleOutput": output,
            "visibleChars": visible_chars,
            "visibleTokens": visible_tokens,
            "visibleTokensPerSecond": visible_tokens / (duration_ms / 1000),
            "visibleCharsPerSecond": visible_chars / (duration_ms / 1000),
            "tokenizer": "regex-v1",
        }
        if proc.stderr:
            record["stderr"] = proc.stderr.strip()
        records.append(record)
    append_jsonl(args.jsonl, records)
    return {"runs": args.runs, "prompt": args.prompt, "models": summarize_visible_records(records), "records": records}


def summarize_visible_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["model"], []).append(record)
    summaries = []
    for model, model_records in grouped.items():
        ok = [record for record in model_records if record.get("status") == "ok"]
        tps = [float(record["visibleTokensPerSecond"]) for record in ok]
        durations = [float(record["durationMs"]) for record in ok]
        summaries.append(
            {
                "model": model,
                "runs": len(model_records),
                "okRuns": len(ok),
                "failures": len(model_records) - len(ok),
                "averageVisibleTokensPerSecond": sum(tps) / len(tps) if tps else None,
                "medianVisibleTokensPerSecond": median(tps) if tps else None,
                "p95VisibleTokensPerSecond": percentile(tps, 0.95) if tps else None,
                "medianDurationMs": median(durations) if durations else None,
            }
        )
    return summaries

def summarize(payload: dict[str, Any]) -> str:
    if "records" in payload:
        lines = []
        for model in payload.get("models", []):
            if not model["okRuns"]:
                lines.append(f"{model['model']}: no successful visible runs")
                continue
            lines.append(
                f"{model['model']}: {model['averageVisibleTokensPerSecond']:.1f} visible tok/s "
                f"(median {model['medianVisibleTokensPerSecond']:.1f}, p95 {model['p95VisibleTokensPerSecond']:.1f}), "
                f"{model['okRuns']}/{model['runs']} ok"
            )
        return "\n".join(lines) if lines else "No model results returned"

    lines = []
    for model in payload.get("models", []):
        avg = model.get("average") or {}
        name = model.get("model") or model.get("selector") or "unknown"
        if not avg:
            lines.append(f"{name}: no successful runs")
            continue
        tps = avg.get("tokensPerSecond")
        ttft = avg.get("ttftMs")
        out = avg.get("outputTokens")
        duration = avg.get("durationMs")
        lines.append(
            f"{name}: {tps:.1f} tok/s, TTFT {ttft:.0f} ms, "
            f"{out:.0f} output tokens in {duration:.0f} ms"
        )
    if not lines:
        lines.append("No model results returned")
    failures = payload.get("failures", 0)
    if failures:
        lines.append(f"Failures: {failures}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = run_visible(args) if args.visible else run_bench(args)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(summarize(payload))
    failed_runs = sum(model.get("failures", 0) for model in payload.get("models", [])) if args.visible else 0
    if failed_runs:
        print(f"visible benchmark had {failed_runs} failed run(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
