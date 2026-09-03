# modeldb source catalog

This catalog documents the ranked source registry seeded by [`db/seed_sources.sql`](../db/seed_sources.sql). It complements the source priority in [`docs/PLAN.md`](PLAN.md) and uses the same ingestion classes:

- **A** — official API, JSON, CSV, ZIP, or parquet endpoint suitable for deterministic parsing.
- **B** — documented but messy source; deterministic fields exist but extraction may need extra care.
- **C** — HTML or RSC extraction source.
- **D** — fragile, hostile, or JS-heavy scrape.

## Ranked catalog

Cadence values come from the `update_cadence` column of the seeded registry.

| Tier | Source id | What it offers | Access URL | Class | Auth | Cadence | Model-id scheme | Gotchas |
|---|---|---|---|---|---|---|---|---|
| 1 | `models_dev` | Canonical-ish provider/model spine: release date, modalities, cost, context, license, open-weights signal. | `https://models.dev/api.json` | A | none | hourly sync | models.dev provider/model IDs; stored as aliases, not canonical authority. | Cost is in USD per million tokens. Treat models.dev IDs as aliases because `modeldb` owns `model.canonical_slug`. |
| 1 | `openrouter` | Router inventory, pricing, context length, Hugging Face bridge, and per-provider routes/latency through `/endpoints`. | `https://openrouter.ai/api/v1/models` | A | none | live | OpenRouter model/router IDs plus `hugging_face_id` when present. | Pricing arrives as per-token strings; normalize into `price_component`. `/endpoints` is separate from the model list and feeds `provider_surface`. |
| 1 | `epoch` | Benchmark ZIP with GPQA Diamond, MATH level 5, MMLU external, SWE-bench Verified, Aider/LiveBench external links, FrontierMath, and capabilities index. | `https://epoch.ai/data/benchmark_data.zip` | A | none | frequent | Benchmark rows identify model names from Epoch CSVs. | ZIP of CSVs; preserve source names and source links. Benchmark names must map into `benchmark`, not ad-hoc columns. |
| 1 | `lmarena` | Official LMArena leaderboard parquet: ELO/rating, confidence intervals, votes, rank, category, publish date. | `https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset` | A | none | daily-ish | Arena model names from leaderboard rows. | Official data is on Hugging Face parquet; configs include text, vision, search, document, webdev, and image/video, with `latest` and `full` splits. Parser needs pandas/pyarrow from `requirements.txt`. |
| 1 | `litellm` | Alias-heavy price and context registry across providers. | `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | A | none | per-release | LiteLLM pricing IDs and provider/model route aliases. | Parse after the canonical spine; this source feeds `model_alias`, `provider_surface`, and price facts rather than creating new canonical models by itself. |
| 1 | `llm_prices` | Clean historical price data in USD per million tokens with tier aliases. | `https://www.llm-prices.com/historical-v1.json` | A | none | on-change | simonw/llm-prices model identifiers and tier aliases. | Best source for temporal price history; use `valid_from` / `valid_to` windows rather than replacing older prices. |
| 2 | `artificialanalysis` | Intelligence, coding, math indices, price, output speed in tokens/sec, and TTFT. Stable model and creator UUIDs. | `https://artificialanalysis.ai/api/v2/data/llms/models` | A | API key | live (72h) | Artificial Analysis model UUIDs and creator UUIDs. | Free API key; 1000 requests/day; use `x-api-key`. Context window may require RSC fallback. |
| 2 | `huggingface` | Open-weight identity: params from safetensors, license, base-model graph, commit SHA, last modified. | `https://huggingface.co/api/models` | A | none | continuous | Hugging Face repo IDs such as `org/model`. | Pull by known HF IDs first; do not full-crawl. Anonymous limit noted in registry is about 500 requests per 5 minutes. |
| 2 | `swebench` | SWE-bench Full, Lite, Verified, and Multimodal percent-resolved results, cost, and per-instance data. | `https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json` | A | none | maintained | SWE-bench leaderboard model names and provider routes. | Repository branch is `master`, not `main`. Keep cost and per-instance data as provenance-bearing facts where parsed. |
| 2 | `aider` | Aider polyglot code-editing leaderboard. | `https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml` | A | none | maintained | `command` field carries provider/model route. | Displayed score is `pass_rate_2`; parse route aliases from `command`. |
| 2 | `deepswe` | DataCurve long-horizon coding-agent benchmark: pass@1, attempts, costs, tokens, steps, and confidence intervals per model/config row. | `https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json` | A | none | maintained | DeepSWE leaderboard model/config labels from static JSON rows. | Methodology and tasks live at `github.com/datacurve-ai/deep-swe`; keep row-level cost/token fields as provenance-bearing facts. |
| 2 | `frontierswe` | FrontierSWE v2 ultra-long-horizon agentic coding benchmark: mean/worst/best pass rates over 5 trials per task (34 tasks, 20-hour budget, proximus harness). | `https://www.frontierswe.com/` | C | none | maintained | Leaderboard `vendor model + harness` title labels. | HTML leaderboard. The source publishes no per-result dates, so stored results keep `measured_at` NULL; any display date is a read-time fallback, never a storage value. |
| 2 | `openvlm` | OpenCompass OpenVLM multimodal/VLM aggregate leaderboard. | `http://opencompass.openxlab.space/assets/OpenVLM.json` | A | none | maintained | OpenVLM leaderboard model labels. | Parse nested VLM benchmark scores into benchmark facts with source links. |
| 2 | `bigcodebench` | BigCodeBench coding aggregate leaderboard. | `https://datasets-server.huggingface.co/rows?dataset=bigcode%2Fbigcodebench-results&config=default&split=train` | A | none | maintained | BigCodeBench row model names. | Datasets-server rows expose complete/instruct aggregate scores; keep row provenance. |
| 2 | `livebench` | Per-question judgments for coding, math, reasoning, instruction following, language, and data analysis. | `https://huggingface.co/datasets/livebench/model_judgment` | A | none | periodic | LiveBench model names in judgment parquet rows. | Verify Hugging Face `lastModified` against repo release list for freshness. |
| 2 | `open_llm_lb` | Archived open-model baselines for IFEval, BBH, MATH-L5, GPQA, MUSR, and MMLU-PRO. | `https://huggingface.co/api/datasets/open-llm-leaderboard/contents` | A | none | FROZEN 2025-03 | Open LLM Leaderboard model/repo names. | Frozen in 2025-03; use as historical baseline only. |
| 2 | `mteb` | MTEB embedding leaderboard results. | `https://huggingface.co/datasets/mteb/results` | A | none | continuous | MTEB result-row model names. | Live source is official HF parquet shards; the stdlib parser accepts caller-supplied aggregate JSON/CSV leaderboard rows and is exclude-from-all (`ingest.run all` skips it). |
| 2 | `vllm` | vLLM supported-architecture registry: which open architectures vLLM ships per release. | `https://raw.githubusercontent.com/vllm-project/vllm/main/vllm/model_executor/models/registry.py` | A | none | per-release | vLLM architecture names parsed from registry source text. | Parsed from source text without executing remote Python; reflects what vLLM supports, not model quality. |
| 2 | `anthropic_api` | Official Anthropic model inventory: ID, display name, created time, max input/max tokens, rich capabilities. | `https://api.anthropic.com/v1/models` | A | API key | on-release | Anthropic API model IDs. | Requires `anthropic-version` header. No pricing in this API. Parser module not implemented yet (stub in `ingest/sources/provider_apis.py`). |
| 2 | `openai_api` | Official OpenAI model inventory. | `https://api.openai.com/v1/models` | A | API key | on-release | OpenAI API model IDs. | Sparse fields only: `id`, `created`, and `owned_by`. Enrich with other sources. Parser module not implemented yet (stub in `ingest/sources/provider_apis.py`). |
| 2 | `gemini_api` | Gemini Developer API model inventory: names, token limits, supported generation methods, base model IDs. | `https://generativelanguage.googleapis.com/v1beta/models` | A | API key | on-release | Gemini model resource names and `baseModelId`. | No pricing in this API. Parser module not implemented yet. |
| 2 | `mistral_api` | Official Mistral model inventory: ID, context, capabilities, deprecation, aliases. | `https://api.mistral.ai/v1/models` | A | API key | on-release | Mistral API model IDs and aliases. | No pricing in this API. Parser module not implemented yet. |
| 3 | `hf_model_card` | Hugging Face raw README cards: YAML frontmatter, license, base model, tags, benchmark tables, and prose. | `https://huggingface.co/{org}/{model}/raw/main/README.md` | B | none | event-driven | HF repo ID plus card-provided aliases/base models. | YAML frontmatter is deterministic; benchmark tables may be Markdown or images. Prose/table extraction may need LLM assistance. Parser module not implemented yet. |
| 3 | `provider_blog` | Launch announcements and provider-reported benchmark tables. | `various` | C | none | event-driven | Blog-specific model names and launch labels. | Mark extracted provider benchmark claims with `benchmark_result.self_reported=1`. Extraction is event-driven and LLM-assisted. Parser module not implemented yet. |
| 3 | `lmarena_mirror` | Clean JSON mirror, including agent arena data not in the official HF dataset. | `https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboards` | A | none | daily | Mirror leaderboard model names. | Convenience and smoke-test source only; non-authoritative relative to official LMArena HF parquet. Parser module not implemented yet. |
| 3 | `scale_seal` | Scale SEAL leaderboards. | `https://labs.scale.com/leaderboard` | D | none | live | Scale leaderboard model labels. | Next/RSC embedded; high signal but scrape-only and fragile. Deferred. Parser module not implemented yet. |
| 3 | `omp_speedtest` | Local OMP speedtest: visible-output TPS from subscription or configured provider routes. | `local:~/.omp/agent/skills/omp-model-speedtest/scripts/omp_speedtest.py` | A | local OMP session | daily | OMP speedtest selector/model labels. | Billing-sensitive: the runner requires `OMP_TPS_ALLOW_PAID=1` (the VPS timer sets it). Exclude-from-all; collection runs via `scripts/collect_omp_tps.py` in the live refresh, not `ingest.run all`. |

## Access cheatsheet

Confirmed live endpoints and access modes from the registry/recon:

| Source | Endpoint | Auth | Suggested env var |
|---|---|---|---|
| `models_dev` | `https://models.dev/api.json` | none | none |
| `openrouter` | `https://openrouter.ai/api/v1/models` | none | none |
| `openrouter` | `https://openrouter.ai/api/v1/models/{model}/endpoints` or equivalent `/endpoints` route used by the parser | none | none |
| `epoch` | `https://epoch.ai/data/benchmark_data.zip` | none | none |
| `lmarena` | Hugging Face parquet resolve URL under `https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset/resolve/main/...` | none | none |
| `swebench` | `https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json` | none | none |
| `aider` | `https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml` | none | none |
| `deepswe` | `https://deepswe.datacurve.ai/artifacts/v1.1/leaderboard-live.json` | none | none |
| `frontierswe` | `https://www.frontierswe.com/` | none | none |
| `mteb` | `https://huggingface.co/datasets/mteb/results` (live parquet; parser takes aggregate JSON/CSV) | none | none |
| `vllm` | `https://raw.githubusercontent.com/vllm-project/vllm/main/vllm/model_executor/models/registry.py` | none | none |
| `llm_prices` | `https://www.llm-prices.com/historical-v1.json` | none | none |
| `openvlm` | `http://opencompass.openxlab.space/assets/OpenVLM.json` | none | none |
| `bigcodebench` | `https://datasets-server.huggingface.co/rows?dataset=bigcode%2Fbigcodebench-results&config=default&split=train` | none | none |
| `artificialanalysis` | `https://artificialanalysis.ai/api/v2/data/llms/models` | `x-api-key` | `ARTIFICIALANALYSIS_API_KEY` |
| `anthropic_api` | `https://api.anthropic.com/v1/models` | API key plus `anthropic-version` header | `ANTHROPIC_API_KEY` |
| `openai_api` | `https://api.openai.com/v1/models` | bearer/API key | `OPENAI_API_KEY` |
| `gemini_api` | `https://generativelanguage.googleapis.com/v1beta/models` | API key | `GEMINI_API_KEY` |
| `mistral_api` | `https://api.mistral.ai/v1/models` | bearer/API key | `MISTRAL_API_KEY` |
| `omp_speedtest` | local skill script; see registry `base_url` | local OMP session | `OMP_TPS_ALLOW_PAID=1` (opt-in for paid runs) |

Notes:
- The `huggingface`, `livebench`, `open_llm_lb`, `openvlm`, `bigcodebench`, and `hf_model_card` sources are unauthenticated in the registry, but Hugging Face-backed parsers should respect rate limits and avoid full crawls.
- `provider_blog` and `scale_seal` are event-driven extraction sources, not regular JSON pulls.
- The OpenRouter model list is unauthenticated; if a future parser uses a private or rate-limited route, keep the public model list behavior separate from key-backed enrichment.
- `ingest/sources/openrouter_endpoints.py` is a DB-pure helper that normalizes pre-fetched OpenRouter `/endpoints` payload arrays; the live endpoint crawler lives in `store/openrouter_endpoints.py` because it is scoped by OpenRouter IDs already in SQLite.
- Live TPS collection for `omp_speedtest` runs through `scripts/collect_omp_tps.py --config scripts/omp_tps_models.json` inside the systemd-driven refresh, never through unattended `ingest.run all`.

## Parser implementation status

From `PARSER_SPECS` in `ingest/run.py` and `build_registry()`:

- Implemented, runnable via `python3 -m ingest.run <source_id>`: `models_dev`, `openrouter`, `epoch`, `lmarena` (needs pandas/pyarrow), `litellm`, `llm_prices`, `artificialanalysis`, `huggingface`, `swebench`, `aider`, `deepswe`, `frontierswe`, `livebench`, `open_llm_lb`, `openvlm`, `bigcodebench`, `mteb`, `vllm`, `omp_speedtest`.
- Registered but not implemented yet (reported as unavailable by the driver): `anthropic_api`, `openai_api`, `gemini_api`, `mistral_api` (stub classes exist in `ingest/sources/provider_apis.py`), `hf_model_card`, `provider_blog`, `lmarena_mirror`, `scale_seal`.
- Exclude-from-all: `mteb` (explicit aggregate imports only) and `omp_speedtest` (local, paid runner).

## Ingestion order

1. **Spine first:** `models_dev` and `openrouter` create the broadest model/provider/price alias surface.
2. **Price history next:** `litellm` and `llm_prices` enrich aliases and temporal prices after canonical candidates exist.
3. **Independent benchmarks:** `epoch`, `lmarena`, `swebench`, `aider`, `deepswe`, `frontierswe`, `openvlm`, `bigcodebench`, `livebench`, `open_llm_lb`, `mteb`, and `vllm` add benchmark/architecture facts with provenance.
4. **Enrichment:** `artificialanalysis`, `huggingface`, and first-party provider APIs add speed, artifact, capability, and inventory details.
5. **Local and extraction-heavy sources:** `omp_speedtest` runs via the VPS refresh scripts; `hf_model_card`, `provider_blog`, `lmarena_mirror`, and `scale_seal` are event-driven, non-spine sources.
