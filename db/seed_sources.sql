-- Seed the source registry from the recon findings.
-- ingestion_class: A=official API/JSON, B=documented but messy, C=HTML/RSC scrape, D=hostile/JS-heavy
-- Priority tiers map to docs/SOURCES.md ranking.

INSERT OR REPLACE INTO source (id, name, base_url, ingestion_class, auth_type, update_cadence, notes) VALUES
-- Tier 1: build deterministic parsers first (clean, official-ish, high coverage)
('models_dev',   'models.dev',                 'https://models.dev/api.json',                                                'A', 'none',    'hourly sync',  'Canonical-ish provider/model spine. release_date, modalities, cost, context, license, open_weights. Cost in $/Mtok.'),
('openrouter',   'OpenRouter',                 'https://openrouter.ai/api/v1/models',                                        'A', 'none',    'live',         'Provider routing, pricing (per-token strings), context, hugging_face_id bridge. /endpoints for per-provider routes+latency.'),
('epoch',        'Epoch AI Benchmarking Hub',  'https://epoch.ai/data/benchmark_data.zip',                                   'A', 'none',    'frequent',     'ZIP of CSVs: gpqa_diamond, math_level_5, mmlu_external, swe_bench_verified, aider/livebench external, frontiermath, capabilities index. Keep Source/Source link.'),
('lmarena',      'LMArena leaderboard',        'https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset',             'A', 'none',    'daily-ish',    'Official HF parquet. ELO/rating, CI, votes, rank, category, publish_date. Configs: text, vision, search, document, webdev, image/video. splits latest/full.'),
('litellm',      'LiteLLM price registry',     'https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json', 'A', 'none', 'per-release', 'Alias-explosion + pricing map. Parse AFTER canonical spine; feeds aliases/provider_surface, not new canonical models.'),
('llm_prices',   'simonw/llm-prices',          'https://www.llm-prices.com/historical-v1.json',                              'A', 'none',    'on-change',    'Clean price history in $/Mtok. Good temporal pricing + tier aliases.'),

-- Tier 2: high value, needs auth or careful normalization
('artificialanalysis', 'Artificial Analysis', 'https://artificialanalysis.ai/api/v2/data/llms/models',                       'A', 'api_key', 'live (72h)',   'Free API key, 1000 req/day, x-api-key header. Intelligence/coding/math indices, price, speed (tok/s), TTFT. Stable model+creator UUIDs. Context window via RSC fallback.'),
('huggingface',  'Hugging Face Hub API',       'https://huggingface.co/api/models',                                           'A', 'none',    'continuous',   'Open-weight identity, params (safetensors), license, base_model graph, sha. Pull by known HF ids first; do not full-crawl. Anonymous ~500 req/5min.'),
('swebench',     'SWE-bench leaderboard',      'https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/master/data/leaderboards.json', 'A', 'none', 'maintained', 'Full/Lite/Verified/Multimodal % resolved + cost + per-instance. Branch is master not main.'),
('aider',        'Aider polyglot leaderboard', 'https://raw.githubusercontent.com/Aider-AI/aider/main/aider/website/_data/polyglot_leaderboard.yml', 'A', 'none', 'maintained', 'Code-editing pass_rate_2 = displayed score. command field carries provider/model route.'),
('livebench',    'LiveBench',                  'https://huggingface.co/datasets/livebench/model_judgment',                   'A', 'none',    'periodic',     'Per-question judgments parquet (coding/math/reasoning/IF/language/data_analysis). Verify HF lastModified vs repo release list for freshness.'),
('open_llm_lb',  'HF Open LLM Leaderboard (archived)', 'https://huggingface.co/api/datasets/open-llm-leaderboard/contents',    'A', 'none',    'FROZEN 2025-03', 'Archived open-model baselines: IFEval, BBH, MATH-L5, GPQA, MUSR, MMLU-PRO. Historical only.'),

-- Provider first-party APIs (auth, official truth, sparse-to-rich)
('anthropic_api','Anthropic Models API',       'https://api.anthropic.com/v1/models',                                        'A', 'api_key', 'on-release',   'id, display_name, created_at, max_input/max_tokens, rich capabilities. No price. anthropic-version header.'),
('openai_api',   'OpenAI Models API',          'https://api.openai.com/v1/models',                                           'A', 'api_key', 'on-release',   'id/created/owned_by only. Inventory existence; enrich elsewhere.'),
('gemini_api',   'Gemini Developer API',       'https://generativelanguage.googleapis.com/v1beta/models',                    'A', 'api_key', 'on-release',   'name, token limits, supportedGenerationMethods, baseModelId. No price.'),
('mistral_api',  'Mistral Models API',         'https://api.mistral.ai/v1/models',                                           'A', 'api_key', 'on-release',   'id, context, capabilities, deprecation, aliases. No price.'),

-- Tier 3: first-party cards/announcements (extraction-heavy)
('hf_model_card','HF model cards (raw README)','https://huggingface.co/{org}/{model}/raw/main/README.md',                    'B', 'none',    'event-driven', 'YAML frontmatter deterministic (license/base_model/tags); benchmark tables markdown OR images. LLM-assisted extraction for prose/tables.'),
('provider_blog','Provider announcements',     'various',                                                                    'C', 'none',    'event-driven', 'Launch posts: self-reported benchmark tables. Mark benchmark_result.self_reported=1. LLM-assisted extraction.'),

-- Convenience / non-authoritative
('lmarena_mirror','arena-ai community mirror', 'https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboards',               'A', 'none',    'daily',        'Clean JSON incl. agent arena (not in official HF dataset). Convenience/smoke-test only; non-authoritative.'),
('scale_seal',   'Scale SEAL leaderboards',    'https://labs.scale.com/leaderboard',                                         'D', 'none',    'live',         'Next/RSC embedded. High signal, scrape-only/fragile. Defer.');
