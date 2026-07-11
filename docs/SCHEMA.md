# modeldb schema reference

This document explains the canonical SQLite schema in [`db/schema.sql`](../db/schema.sql). The design follows the four-layer plan in [`docs/PLAN.md`](PLAN.md): deterministic ingest writes raw snapshots and source-native records, resolution builds canonical identity, SQLite stores provenance-bearing facts, and consumers query the spine.

## Core rationale

`modeldb` keeps source truth and canonical interpretation separate:

- **Raw snapshots are append-only.** A source payload is stored under `data/raw/<source>/` and registered in `source_snapshot` by URL, parser version, and SHA-256 content hash. Parser upgrades can re-read the raw payload without losing what the source served.
- **Canonical models are abstract releases.** A `model` row represents a model release, independent of API endpoint, router surface, hosted region, open-weight repository, or quantized file variant.
- **Aliases are never discarded.** Every source-specific identifier string becomes a `model_alias` row, even after it resolves to a canonical model.
- **Facts carry provenance.** Prices, capabilities, benchmark results, provider surfaces, artifacts, and aliases point back to a `source_snapshot_id` when the fact came from a source snapshot. Fact rows also carry confidence and/or validity windows where the schema needs them.
- **Benchmark run settings are not models.** Effort, thinking mode, benchmark category, and similar evaluation conditions live in `benchmark_result.eval_condition_json`, not in new `model` rows.
- **Quantization is an artifact variant.** File-level formats and quantizations belong in `artifact_variant`, attached to a `model_artifact`, not in separate canonical model identities.
- **Provider claims are kept but marked.** Benchmark rows extracted from launch posts or provider claims use `benchmark_result.self_reported=1`; independent aggregators use `0`.

## Source and snapshot tables

### `source`

Registry of known data sources, seeded by [`db/seed_sources.sql`](../db/seed_sources.sql).

Purpose:
- Defines the stable `source.id` used by parser classes and provenance columns.
- Records access class, auth type, cadence, and source-specific notes.

Non-obvious columns:
- `ingestion_class`: `A` clean API/file, `B` documented but messy, `C` HTML/RSC scrape, `D` hostile or JS-heavy.
- `auth_type`: source-level access mode such as `none`, `api_key`, or `bearer`; specific environment variables are documented in [`docs/SOURCES.md`](SOURCES.md).
- `notes`: source registry facts that parsers and docs should preserve, such as branch names, endpoint quirks, benchmark fields, and source authority.

### `source_snapshot`

Append-only record of fetched source payloads.

Purpose:
- Stores a durable reference to each raw body returned by a source URL.
- Makes parser runs idempotent through `UNIQUE (source_id, url, content_hash)`.
- Provides the provenance anchor used by records, aliases, provider surfaces, prices, capabilities, and benchmarks.

Non-obvious columns:
- `content_hash`: SHA-256 of the raw body; this is the dedupe key for identical payloads.
- `parser_version`: the parser version that created this snapshot row, so parser changes are auditable.
- `raw_path`: repo-relative path under `data/raw/<source>/`; raw data is gitignored but reproducible.
- `etag` and `last_modified`: optional HTTP cache headers captured by parsers when available.

## Canonical identity tables

### `organization`

Developer or provider organization registry.

Purpose:
- Normalizes model developers such as `anthropic`, `openai`, `meta`, and `google`.
- Gives canonical model rows a stable `developer_id` instead of relying on source display strings.

Non-obvious columns:
- `id`: lowercase stable slug, not an integer surrogate.
- `aliases_json`: source or human variants such as alternate company names and spellings.

### `model`

Canonical abstract model release.

Purpose:
- Represents a model release independent of where it is served or packaged.
- Owns the project-level `canonical_slug`, not delegated to any upstream source.

Non-obvious columns:
- `canonical_slug`: unique identity in `{developer}/{family}-{variant}[@{snapshot}]` form, for example `anthropic/claude-sonnet-4.5@2025-09-29`.
- `generation`: text, not a float, so versions like `3.1`, `4.5`, and `1.0-preview` are not mangled.
- `tier_or_variant`: tier names such as `sonnet`, `opus`, `flash`, or `maverick`.
- `parameter_scale`: human-scale parameter count or architecture descriptor such as `405b`, `17b`, or `128e` when known.
- `training_role`: role such as `base`, `instruct`, `chat`, or `reasoning`.
- `snapshot_date`: distinguishes dated model snapshots from moving aliases.
- `stability`: state such as `pinned`, `latest_alias`, `preview`, `deprecated`, or `retired`.
- `open_weights`: tri-state `0/1/NULL`; unknown is different from closed.
- `canonical_confidence`: resolution confidence class: `verified`, `probable`, or `manual_review`.

Important invariant:
- A different provider endpoint, router slug, region, benchmark effort, or quantized file does not by itself create a new `model` row.

## Aliases and resolution tables

### `model_alias`

Every source-specific identifier string known to the system.

Purpose:
- Preserves exact source strings forever.
- Bridges source-native names to canonical `model`, provider surfaces, or model artifacts.
- Lets moving aliases such as `latest` remain queryable across time.

Non-obvious columns:
- `alias_string`: raw exact string from the source.
- `alias_normalized`: normalized string for matching and dedupe.
- `alias_kind`: classifier such as `api_model_id`, `display_name`, `router_id`, `canonical_slug`, `hf_repo_id`, `bedrock_id`, `vertex_id`, `pricing_id`, `arena_model`, or `latest_alias`.
- `model_id`: nullable until resolution attaches the alias to a canonical model.
- `provider_surface_id`: optional bridge when the alias names a serving endpoint rather than the abstract model.
- `artifact_id`: optional bridge when the alias names an open-weight artifact.
- `valid_from` / `valid_to`: validity window for aliases that change meaning over time.
- `resolution_method`: evidence class, for example `exact_provider_doc`, `hf_id_bridge`, `canonical_slug_bridge`, `source_base_model`, `normalized_match`, or `manual_override`.
- `confidence`: numeric confidence for the resolution.
- `source_snapshot_id`, `first_seen_at`, `last_seen_at`: provenance and observation window.

Important invariant:
- Aliases are never overwritten or thrown away. If resolution improves, the alias row remains as evidence; moving alias transitions are tracked in `alias_history`.

### `alias_history`

Temporal mapping for moving aliases.

Purpose:
- Tracks what canonical model an alias referred to over time.
- Keeps `latest`, `chat-latest`, and similar moving targets historically useful.

Non-obvious columns:
- `alias_id`: the alias whose meaning changed.
- `observed_from` / `observed_to`: observed validity interval.
- `evidence_snapshot_id`: source snapshot that supported the observation.
- `confidence`: confidence for this specific temporal mapping.

### `entity_resolution_queue`

Review queue for ambiguous source records.

Purpose:
- Stores candidate merges that deterministic matching could not safely decide.
- Allows a future agent or human review step to accept or reject candidates.

Non-obvious columns:
- `source_record_id`: source record being resolved.
- `candidate_model_id`: proposed canonical model.
- `features_json`: match features used to justify the candidate, such as normalized strings, HF IDs, dates, provider IDs, or scores.
- `status`: `pending`, `accepted`, or `rejected`.

## Source record table

### `source_model_record`

One model-like row as one source sees it.

Purpose:
- Stores parser output before canonical resolution.
- Keeps the raw per-record JSON alongside parsed fields.
- Lets parsers stay deterministic and source-native; they do not invent canonical model IDs.

Non-obvious columns:
- `source_snapshot_id`: links the record to the exact fetched payload.
- `source_model_id`: source-native identifier.
- `display_name`: human label when provided.
- `provider_name`: source-native provider or creator label when provided.
- `raw_record_json`: exact record-level JSON serialization preserved by the parser.
- `parsed_fields_json`: normalized source-specific fields useful for resolution and fact extraction.
- `model_alias_id`: optional link to the alias row created from this source record.

Important invariant:
- The unique key is `(source_snapshot_id, source_model_id)`: the same source model ID can appear in many snapshots, and that is expected.

## Provider surface and artifact tables

### `provider_surface`

A way a canonical model is served by a provider or router.

Purpose:
- Separates abstract model identity from endpoint IDs exposed by Anthropic, OpenAI, Gemini, Mistral, OpenRouter, Bedrock, Vertex, Azure, Groq, Together, and similar surfaces.
- Supports provider-specific prices, capabilities, routing metadata, and aliases.

Non-obvious columns:
- `provider_id`: provider slug such as `anthropic`, `amazon-bedrock`, `google-vertex`, or `openrouter`.
- `surface_type`: category such as `first_party`, `openrouter`, `bedrock`, `vertex`, `azure`, `groq`, or `together`.
- `region`: optional regional endpoint dimension.
- `endpoint_model_id`: provider-native model ID used at the API surface.
- `model_id`: nullable until resolution connects the endpoint to a canonical model.
- `metadata_json`: route metadata such as latency, modality, limits, or provider-specific details.

### `model_artifact`

Open-weight repository or file-set identity.

Purpose:
- Represents a source-published artifact such as a Hugging Face repo or weights URL.
- Keeps packaging and open-weight details separate from the canonical abstract model.

Non-obvious columns:
- `artifact_ref`: artifact identifier, for example an HF repo ID.
- `artifact_type`: `hf_repo`, `file_set`, `weights_url`, or another source-specific package type.
- `gated`: text because sources may expose more than boolean access states.
- `license`, `sha`, `last_modified`: artifact-level metadata, especially from Hugging Face.
- `metadata_json`: extra source-specific fields such as tags, base model links, or card metadata.

### `artifact_variant`

File-level variant under a model artifact.

Purpose:
- Stores quantization, format, parameter count, and file pattern details for a specific artifact.

Non-obvious columns:
- `quantization`: values such as `fp8`, `gguf:q4_k_m`, or `awq`.
- `format`: file or package format.
- `parameter_count`: integer when source metadata provides it.
- `file_pattern`: pattern or file family for the variant.

Important invariant:
- Quantized files and formats are variants of an artifact, not separate canonical `model` rows.

## Fact tables

### `model_capability`

Capabilities observed for a model.

Purpose:
- Stores capabilities such as context window, vision support, tool calling, reasoning support, or max output.

Non-obvious columns:
- `capability`: key such as `context_window`, `vision`, `tool_call`, `reasoning`, or `max_output`.
- `value`: text to preserve source-native values without premature type decisions.
- `source_snapshot_id`: provenance for the capability value.
- `confidence`: numeric trust score for the extraction or resolution.

### `price_component`

Provider/model price components, raw and normalized.

Purpose:
- Stores token prices and non-token price components with provenance and validity windows.
- Allows temporal price history by keeping `valid_from` and `valid_to` instead of replacing old prices.

Non-obvious columns:
- `model_id`: canonical model when known.
- `provider_surface_id`: endpoint-specific price when known.
- `source_id`: price source such as `models_dev`, `openrouter`, `litellm`, or `llm_prices`.
- `component`: component such as `input_token`, `output_token`, `cache_read`, `cache_write`, `web_search`, or `image`.
- `unit`: original source unit such as `token`, `1m_tokens`, `request`, `second`, or `image`.
- `amount`: raw amount in the source unit.
- `normalized_usd_per_1m_tokens`: normalized value for token components.
- `tier_condition_json`: price tier conditions such as context-length thresholds.
- `valid_from` / `valid_to`: price validity window.
- `source_snapshot_id`: exact source payload that produced the price.

### `benchmark`

Benchmark catalog.

Purpose:
- Defines benchmark identities and their default metrics.
- Keeps result rows compact and consistent across sources.

Non-obvious columns:
- `id`: stable benchmark slug such as `gpqa_diamond`, `mmlu_pro`, `swe_bench_verified`, or `lmarena_text_overall`.
- `category`: broad category such as `coding`, `math`, `reasoning`, `agentic`, or `arena_elo`.
- `metric_default`: source-normalized default metric, for example `pass@1`, `accuracy`, `elo`, or `percent_resolved`.
- `higher_is_better`: integer boolean, default `1`.

### `benchmark_result`

Observed benchmark score for a model or provider surface.

Purpose:
- Stores independent and self-reported results while preserving provenance, metric, conditions, rank, and uncertainty.

Non-obvious columns:
- `model_id`: canonical model when the result resolves at model level.
- `provider_surface_id`: serving endpoint when a benchmark result is route/provider-specific.
- `benchmark_id`: benchmark catalog key.
- `score`, `metric`, `rank`, `ci`, `votes`: source-specific result data.
- `eval_condition_json`: run conditions such as `{effort:'high', thinking:true, category:'coding'}`. Effort/thinking variants belong here, not in `model`.
- `self_reported`: `1` for provider-announcement claims, `0` for independent aggregator numbers.
- `measured_at`: source-provided measurement or publication time.
- `source_snapshot_id`: exact source payload that produced the result.
- `raw_record_json`: record-level result payload.

## Example queries

### Price history for a model

```sql
SELECT
  m.canonical_slug,
  ps.provider_id,
  ps.surface_type,
  pc.component,
  pc.amount,
  pc.unit,
  pc.normalized_usd_per_1m_tokens,
  pc.valid_from,
  pc.valid_to,
  pc.source_id,
  ss.fetched_at
FROM price_component AS pc
JOIN model AS m ON m.id = pc.model_id
LEFT JOIN provider_surface AS ps ON ps.id = pc.provider_surface_id
LEFT JOIN source_snapshot AS ss ON ss.id = pc.source_snapshot_id
WHERE m.canonical_slug = 'anthropic/claude-sonnet-4.5@2025-09-29'
ORDER BY pc.component, pc.valid_from, ss.fetched_at;
```

### All aliases for a canonical model

```sql
SELECT
  s.name AS source,
  ma.alias_kind,
  ma.alias_string,
  ma.resolution_method,
  ma.confidence,
  ma.first_seen_at,
  ma.last_seen_at
FROM model_alias AS ma
JOIN source AS s ON s.id = ma.source_id
JOIN model AS m ON m.id = ma.model_id
WHERE m.canonical_slug = 'openai/gpt-5'
ORDER BY ma.alias_kind, ma.source_id, ma.alias_string;
```

### Top models on a benchmark with provenance

```sql
SELECT
  b.name AS benchmark,
  m.canonical_slug,
  br.score,
  br.metric,
  br.rank,
  br.ci,
  br.votes,
  br.self_reported,
  br.eval_condition_json,
  ss.source_id,
  ss.url,
  ss.fetched_at
FROM benchmark_result AS br
JOIN benchmark AS b ON b.id = br.benchmark_id
LEFT JOIN model AS m ON m.id = br.model_id
LEFT JOIN source_snapshot AS ss ON ss.id = br.source_snapshot_id
WHERE br.benchmark_id = 'swe_bench_verified'
ORDER BY br.score DESC, br.rank ASC
LIMIT 20;
```

### Models released since a date

```sql
SELECT
  canonical_slug,
  developer_id,
  family,
  generation,
  tier_or_variant,
  release_date,
  open_weights,
  canonical_confidence
FROM model
WHERE release_date >= '2026-01-01'
ORDER BY release_date DESC, canonical_slug;
```
