"""FrontierSWE leaderboard source parser."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ingest.base import SourceModelRecord, SourceParser


SOURCE_ID = "frontierswe"
BENCHMARK_ID = "frontierswe_v2"
LIVE_URL = "https://www.frontierswe.com/"
USER_AGENT = "modeldb-ingest/0.1"

KNOWN_VENDORS: tuple[str, ...] = (
    "Moonshot AI",
    "Thinking Machines",
    "Anthropic",
    "OpenAI",
    "Z.ai",
    "xAI",
    "Google",
    "Qwen",
    "DeepSeek",
    "Meta",
)

_TITLE_RE = re.compile(
    r"^(?P<vendor_model>.+?)\s*\+\s*(?P<harness>.+?):\s*mean@5\s*(?P<mean>[\d.]+)%,\s*worst@5\s*(?P<worst>[\d.]+)%,\s*best@5\s*(?P<best>[\d.]+)%"
)


def _slug(value: object) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"


def _split_vendor_model(raw: str) -> tuple[str, str]:
    raw = raw.strip()
    for vendor in KNOWN_VENDORS:
        if raw.startswith(vendor + " "):
            return vendor, raw[len(vendor) + 1 :].strip()
    parts = raw.split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return "unknown", raw


def _parse_duration_hours(val_str: str | None) -> float | None:
    if not val_str:
        return None
    val_str = val_str.strip().lower()
    if val_str.endswith("h"):
        try:
            return float(val_str[:-1])
        except ValueError:
            return None
    if val_str.endswith("m"):
        try:
            return round(float(val_str[:-1]) / 60.0, 2)
        except ValueError:
            return None
    try:
        return float(val_str)
    except ValueError:
        return None


class FrontierSWEParser(SourceParser):
    """Parse FrontierSWE HTML leaderboard into source-native model records."""

    source_id = SOURCE_ID
    parser_version = "0.1.0"

    def fetch(self) -> tuple[str, bytes, dict]:
        request = Request(LIVE_URL, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=30) as response:
                headers = dict(response.headers)
                return LIVE_URL, response.read(), headers
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"FrontierSWE live fetch failed from {LIVE_URL}: {exc}") from exc

    def parse(self, raw: bytes, snapshot_id: int) -> Iterator[SourceModelRecord]:
        text = raw.decode("utf-8", errors="replace")

        # Find all row divs by their title attribute which contains mean@5
        row_pat = re.compile(
            r'<div\s+title="(?P<title>[^"]+:\s*mean@5[^"]+)"[^>]*>(?P<body>.*?)</div>\s*<div class="relative h-5',
            re.S,
        )

        matches = list(row_pat.finditer(text))
        if not matches:
            # Fallback pattern if surrounding markup shifts
            row_pat_fallback = re.compile(
                r'title="(?P<title>[^"]+:\s*mean@5[^"]+)"',
                re.S,
            )
            for m in row_pat_fallback.finditer(text):
                title = m.group("title")
                t_match = _TITLE_RE.match(title)
                if not t_match:
                    continue
                vendor, model_name = _split_vendor_model(t_match.group("vendor_model"))
                harness = t_match.group("harness").strip()
                mean_val = float(t_match.group("mean"))
                worst_val = float(t_match.group("worst"))
                best_val = float(t_match.group("best"))

                parsed_fields = {
                    "benchmark_id": BENCHMARK_ID,
                    "benchmark_name": "FrontierSWE v2",
                    "category": "coding",
                    "metric": "percent_resolved",
                    "score": mean_val,
                    "worst_at_5": worst_val,
                    "best_at_5": best_val,
                    "model_name": model_name,
                    "model_version": model_name,
                    "vendor": vendor,
                    "provider_name": vendor,
                    "harness": harness,
                    "n_tasks": 34,
                    "n_trials": 5,
                    "budget_hours": 20,
                    "measured_at": None,
                }
                yield SourceModelRecord(
                    source_model_id=f"{BENCHMARK_ID}::{_slug(model_name)}",
                    display_name=model_name,
                    provider_name=vendor,
                    raw_record_json=json.dumps({"title": title}, sort_keys=True),
                    parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
                )
            return

        for m in matches:
            title = m.group("title")
            body = m.group("body")

            t_match = _TITLE_RE.match(title)
            if not t_match:
                continue

            vendor, model_name = _split_vendor_model(t_match.group("vendor_model"))
            harness = t_match.group("harness").strip()
            mean_val = float(t_match.group("mean"))
            worst_val = float(t_match.group("worst"))
            best_val = float(t_match.group("best"))

            rank_match = re.search(r'class="[^"]*tabular-nums[^"]*">\s*(\d+)\s*</span>', body)
            rank = int(rank_match.group(1)) if rank_match else None

            ci_match = re.search(r'±(?:<!-- -->)?\s*([\d.]+)', body)
            ci = float(ci_match.group(1)) if ci_match else None

            cost_match = re.search(r'\$([\d.]+)', body)
            cost = float(cost_match.group(1)) if cost_match else None

            time_match = re.search(r'>([\d.]+[hm])<', body)
            time_raw = time_match.group(1) if time_match else None
            duration_hours = _parse_duration_hours(time_raw)

            raw_dict = {
                "title": title,
                "rank": rank,
                "ci": ci,
                "avg_cost_usd": cost,
                "time_str": time_raw,
                "avg_duration_hours": duration_hours,
            }

            parsed_fields = {
                "benchmark_id": BENCHMARK_ID,
                "benchmark_name": "FrontierSWE v2",
                "category": "coding",
                "metric": "percent_resolved",
                "score": mean_val,
                "worst_at_5": worst_val,
                "best_at_5": best_val,
                "ci": ci,
                "rank": rank,
                "avg_cost_usd": cost,
                "avg_duration_hours": duration_hours,
                "model_name": model_name,
                "model_version": model_name,
                "vendor": vendor,
                "provider_name": vendor,
                "harness": harness,
                "n_tasks": 34,
                "n_trials": 5,
                "budget_hours": 20,
                "measured_at": None,
            }

            yield SourceModelRecord(
                source_model_id=f"{BENCHMARK_ID}::{_slug(model_name)}",
                display_name=model_name,
                provider_name=vendor,
                raw_record_json=json.dumps(raw_dict, sort_keys=True),
                parsed_fields_json=json.dumps(parsed_fields, sort_keys=True),
            )
