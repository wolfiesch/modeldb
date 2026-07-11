# New Model Drop Research Rule

Use this checklist when a model has just launched or the user names a model to add.

## Research Order

1. **Identify the model string set**
   - Capture the provider display name, API id, router id, family, variant, snapshot date, and any marketing name.
   - Normalize likely aliases but keep the exact strings for `model_alias.alias_string`.
   - Note whether the model is first-party hosted, routed through aggregators, open-weight, preview, latest alias, or deprecated.

2. **Check deterministic registry sources first**
   - `models_dev` (`https://models.dev/api.json`): release date, modalities, cost in $/Mtok, context, license, `open_weights`, provider id, and model ids.
   - `openrouter` (`https://openrouter.ai/api/v1/models`): router id, canonical slug hints, `hugging_face_id`, context length, pricing prompt/completion strings, architecture input/output modalities, supported parameters, and provider routing.
   - `litellm`: alias explosion, context window, provider routes, and pricing ids. Treat as alias/provider-surface enrichment after canonical identity exists.
   - `llm_prices`: historical token price entries in $/Mtok and effective dates.
   - `swebench` and `aider`: coding benchmark appearance, cost, command/provider route, and displayed score fields when available.

3. **Check provider-owned launch evidence**
   - Provider docs model pages: API ids, context window, max output, modalities, tool/function calling, pricing, deprecation or preview status.
   - Provider blog or launch announcement: release date, positioning, self-reported benchmark tables, speed claims, safety notes, and chart images.
   - Provider APIs when authenticated sources are available: `anthropic_api`, `openai_api`, `gemini_api`, `mistral_api` for official inventory and limits.

4. **Check open-weight evidence when relevant**
   - Hugging Face raw README: `https://huggingface.co/{org}/{model}/raw/main/README.md`.
   - HF model card YAML frontmatter: license, base model, tags, pipeline tags, datasets, language, and gated status.
   - HF Hub API: safetensors parameter metadata, author, sha, last modified, siblings, and base model graph.
   - Preserve the repo id as `model_artifact.artifact_ref` and `model_alias.alias_kind = 'hf_repo_id'`.

5. **Check independent benchmark aggregators as they update**
   - `artificialanalysis`: intelligence/coding/math indices, price, speed tokens/sec, TTFT, creator UUID, model UUID, and context window fallback.
   - `lmarena`: ELO/rating, confidence interval, votes, rank, category, and publish date from official HF parquet configs.
   - `epoch`: benchmark CSV rows for GPQA Diamond, MATH Level 5, MMLU external, SWE-bench Verified, Aider/LiveBench external, FrontierMath, and capability index.
   - `livebench`, `open_llm_lb`, `scale_seal`, and `lmarena_mirror`: use as secondary or historical enrichment according to source notes.

## Provenance Requirements

- Capture raw payloads through ingest whenever a parser exists; the parser writes `source_snapshot` and raw files under `data/raw/<source>/`.
- For manual or LLM-assisted extraction from provider announcements, create or reference a `source_snapshot` tied to `provider_blog` or `hf_model_card` before inserting structured facts.
- Preserve exact URLs, publication dates, and source ids in notes during research so inserted rows can carry `source_snapshot_id` or `source_id`.
- Store raw benchmark table rows or relevant snippets in `benchmark_result.raw_record_json` when extracting from prose, markdown, or images.

## Self-Reported Benchmark Handling

- Treat provider blog and launch-page benchmark claims as useful but not independent.
- Insert launch claims into `benchmark_result` with `self_reported = 1`.
- Put effort, tool use, thinking mode, pass count, or special settings in `benchmark_result.eval_condition_json` instead of creating a new canonical model.
- Prefer independent rows from LMArena, Artificial Analysis, Epoch, SWE-bench, Aider, and LiveBench for headline comparisons when present.

## Missing-Source Notes

Record sources that do not yet contain the model. Use that absence to schedule later enrichment, not to block the initial canonical row when first-party identity is clear.
