# modeldb source catalog

This catalog documents the ranked source registry seeded by [`db/seed_sources.sql`](../db/seed_sources.sql). It complements the source priority in [`docs/PLAN.md`](PLAN.md) and uses the same ingestion classes:

- **A** — official API, JSON, CSV, ZIP, or parquet endpoint suitable for deterministic parsing.
- **B** — documented but messy source; deterministic fields exist but extraction may need extra care.
- **C** — HTML or RSC extraction source.
- **D** — fragile, hostile, or JS-heavy scrape.

## Ranked catalog

| Tier | Source id | What it offers | Access URL | Class | Auth | Model-id scheme | Gotchas |
|---|---|---|---|---|---|---|---|
| 1 | `models_dev` | Canonical-ish provider/model spine: release date, modalities, cost, context, license, open-weights signal. | `https://models.dev/api.json` | A | none | models.dev provider/model IDs; stored as aliases, not canonical authority. | Cost is in USD per million tokens. Treat models.dev IDs as aliases because `modeldb` owns `model.canonical_slug`. |
| 1 | `openrouter` | Router inventory, pricing, context length, Hugging Face bridge, and per-provider routes/latency through `/endpoints`. | `https://openrouter.ai/api/v1/models` | A | none | OpenRouter model/router IDs plus `hugging_face_id` when present. | Pricing arrives as per-token strings; normalize into `price_component`. `/endpoints` is separate from the model list and feeds `provider_surface`. |
| 1 | `epoch` | Benchmark ZIP with GPQA Diamond, MATH level 5, MMLU external, SWE-bench Verified, Aider/LiveBench external links, FrontierMath, and capabilities index. | `https://epoch.ai/data/benchmark_data.zip` | A | none | Benchmark rows identify model names from Epoch CSVs. | ZIP of CSVs; preserve source names and source links. Benchmark names must map into `benchmark`, not ad-hoc columns. |
| 1 | `lmarena` | Official LMArena leaderboard parquet: ELO/rating, confidence intervals, votes, rank, category, publish date. | `https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset` | A | none | Arena model names from leaderboard rows. | Official data is on Hugging Face parquet; configs include text, vision, search, document, webdev, and image/video, with `latest` and `full` splits. |
| 1 | `litellm` | Alias-heavy price and context registry across providers. | `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json` | A | none | LiteLLM pricing IDs and provider/model route aliases. | Parse after the canonical spine; this source feeds `model_alias`, `provider_surface`, and price facts rather than creating new canonical models by itself. |
| 1 | `llm_prices` | Clean historical price data in USD per million tokens with tier aliases. | `https://www.llm-prices.com/historical-v1.json` | A | none | simonw/llm-prices model identifiers and tier aliases. | Best source for temporal price history; use `valid_from` / `valid_to` windows rather than replacing older prices. |
| 2 | `artificialanalysis` | Intelligence, coding, math indices, price, output speed in tokens/sec, and TTFT. Stable model and creator UUIDs. | `https://artificialanalysis.ai/api/v2/data/llms/models` | A | API key | Artificial Analysis model UUIDs and creator UUIDs. | Free API key; 1000 requests/day; use `x-api-key`. Context window may require RSC fallback. |
| 2 | `huggingface` | Open-weight identity: params from safetensors, license, base-model graph, commit SHA, last modified. | `https://huggingface.co/api/models` | A | none | Hugging Face repo IDs such as `org/model`. | Pull by known HF IDs first; do not full-crawl. Anonymous limit noted in registry is about 500 requests per 5 minutes. |
| 2 | `swebench` | SWE-bench Full, Lite, Verified, and Multimodal percent-resolved results, cost, and per-instance data. | `https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json` | A | none | SWE-bench leaderboard model names and provider routes. | Repository branch is `master`, not `main`. Keep cost and per-instance data as provenance-bearing facts where parsed. |
| 2 | `aider` | Aider polyglot code-editing leaderboard. | `https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml` | A | none | `command` field carries provider/model route. | Displayed score is `pass_rate_2`; parse route aliases from `command`. |
| 2 | `livebench` | Per-question judgments for coding, math, reasoning, instruction following, language, and data analysis. | `https://huggingface.co/datasets/livebench/model_judgment` | A | none | LiveBench model names in judgment parquet rows. | Verify Hugging Face `lastModified` against repo release list for freshness. |
| 2 | `open_llm_lb` | Archived open-model baselines for IFEval, BBH, MATH-L5, GPQA, MUSR, and MMLU-PRO. | `https://huggingface.co/api/datasets/open-llm-leaderboard/contents` | A | none | Open LLM Leaderboard model/repo names. | Frozen in 2025-03; use as historical baseline only. |
| 2 | `anthropic_api` | Official Anthropic model inventory: ID, display name, created time, max input/max tokens, rich capabilities. | `https://api.anthropic.com/v1/models` | A | API key | Anthropic API model IDs. | Requires `anthropic-version` header. No pricing in this API. |
| 2 | `openai_api` | Official OpenAI model inventory. | `https://api.openai.com/v1/models` | A | API key | OpenAI API model IDs. | Sparse fields only: `id`, `created`, and `owned_by`. Enrich with other sources. |
| 2 | `gemini_api` | Gemini Developer API model inventory: names, token limits, supported generation methods, base model IDs. | `https://generativelanguage.googleapis.com/v1beta/models` | A | API key | Gemini model resource names and `baseModelId`. | No pricing in this API. |
| 2 | `mistral_api` | Official Mistral model inventory: ID, context, capabilities, deprecation, aliases. | `https://api.mistral.ai/v1/models` | A | API key | Mistral API model IDs and aliases. | No pricing in this API. |
| 3 | `hf_model_card` | Hugging Face raw README cards: YAML frontmatter, license, base model, tags, benchmark tables, and prose. | `https://huggingface.co/{org}/{model}/raw/main/README.md` | B | none | HF repo ID plus card-provided aliases/base models. | YAML frontmatter is deterministic; benchmark tables may be Markdown or images. Prose/table extraction may need LLM assistance. |
| 3 | `provider_blog` | Launch announcements and provider-reported benchmark tables. | `various` | C | none | Blog-specific model names and launch labels. | Mark extracted provider benchmark claims with `benchmark_result.self_reported=1`. Extraction is event-driven and LLM-assisted. |
| 3 | `lmarena_mirror` | Clean JSON mirror, including agent arena data not in the official HF dataset. | `https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboards` | A | none | Mirror leaderboard model names. | Convenience and smoke-test source only; non-authoritative relative to official LMArena HF parquet. |
| 3 | `scale_seal` | Scale SEAL leaderboards. | `https://labs.scale.com/leaderboard` | D | none | Scale leaderboard model labels. | Next/RSC embedded; high signal but scrape-only and fragile. Deferred. |

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
| `llm_prices` | `https://www.llm-prices.com/historical-v1.json` | none | none |
| `artificialanalysis` | `https://artificialanalysis.ai/api/v2/data/llms/models` | `x-api-key` | `ARTIFICIALANALYSIS_API_KEY` |
| `anthropic_api` | `https://api.anthropic.com/v1/models` | API key plus `anthropic-version` header | `ANTHROPIC_API_KEY` |
| `openai_api` | `https://api.openai.com/v1/models` | bearer/API key | `OPENAI_API_KEY` |
| `gemini_api` | `https://generativelanguage.googleapis.com/v1beta/models` | API key | `GEMINI_API_KEY` |
| `mistral_api` | `https://api.mistral.ai/v1/models` | bearer/API key | `MISTRAL_API_KEY` |

Notes:
- The `huggingface`, `livebench`, `open_llm_lb`, and `hf_model_card` sources are unauthenticated in the registry, but parsers should respect Hugging Face rate limits and avoid full crawls.
- `provider_blog` and `scale_seal` are event-driven extraction sources, not regular JSON pulls.
- The OpenRouter model list is unauthenticated; if a future parser uses a private or rate-limited route, keep the public model list behavior separate from key-backed enrichment.

## Ingestion order

1. **Spine first:** `models_dev` and `openrouter` create the broadest model/provider/price alias surface.
2. **Price history next:** `litellm` and `llm_prices` enrich aliases and temporal prices after canonical candidates exist.
3. **Independent benchmarks:** `epoch`, `lmarena`, `swebench`, `aider`, `livebench`, and `open_llm_lb` add benchmark facts with provenance.
4. **Enrichment:** `artificialanalysis`, `huggingface`, and first-party provider APIs add speed, artifact, capability, and inventory details.
5. **Extraction-heavy sources:** `hf_model_card`, `provider_blog`, `lmarena_mirror`, and `scale_seal` are event-driven, non-spine sources.
