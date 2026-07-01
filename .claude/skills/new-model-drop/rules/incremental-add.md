# New Model Drop Incremental Add Rule

Use this sequence to add one named model without rebuilding the whole corpus.

## 1. Initialize or Confirm the Database

- Create the SQLite spine when missing:

```bash
python -m db.init
```

- Confirm the relevant source ids exist in `source`: `models_dev`, `openrouter`, `epoch`, `lmarena`, `litellm`, `llm_prices`, `artificialanalysis`, `huggingface`, `swebench`, `aider`, `livebench`, `open_llm_lb`, `anthropic_api`, `openai_api`, `gemini_api`, `mistral_api`, `hf_model_card`, `provider_blog`, `lmarena_mirror`, `scale_seal`.

## 2. Run Only Relevant Parsers

Prefer targeted ingest before `all` on launch day:

```bash
python -m ingest.run models_dev
python -m ingest.run openrouter
python -m ingest.run llm_prices
python -m ingest.run litellm
python -m ingest.run swebench
python -m ingest.run aider
```

Add benchmark/enrichment sources when they are likely to have updated:

```bash
python -m ingest.run lmarena
python -m ingest.run epoch
python -m ingest.run artificialanalysis
python -m ingest.run huggingface
python -m ingest.run all
```

A source reported as `not yet implemented` is not a failure. Continue with available snapshots and fill launch-critical gaps from first-party evidence.

## 3. Run Resolution

Run the resolver after ingest so source-native rows become canonical model rows, aliases, provider surfaces, artifacts, prices, capabilities, and queued ambiguities:

```bash
python -m resolve.run
```

Expected resolver behavior:

- Normalize each `source_model_record.source_model_id` into `model_alias.alias_normalized`.
- Attach exact API ids, router ids, display names, HF repo ids, pricing ids, and canonical slug hints to `model_alias`.
- Use bridges in this order when possible: exact provider docs, Hugging Face id, canonical slug, source base model, normalized match, manual override.
- Create `entity_resolution_queue` rows for ambiguous candidates instead of guessing.

## 4. Verify the Canonical Row

Query the canonical row and aliases before manual filling:

```sql
SELECT id, canonical_slug, developer_id, family, generation, tier_or_variant,
       release_date, snapshot_date, stability, open_weights, canonical_confidence,
       created_at, updated_at
FROM model
WHERE canonical_slug LIKE '%<model-fragment>%'
ORDER BY updated_at DESC;

SELECT ma.source_id, ma.alias_string, ma.alias_kind, ma.confidence,
       ma.resolution_method, ma.first_seen_at, ma.last_seen_at
FROM model_alias ma
JOIN model m ON m.id = ma.model_id
WHERE m.canonical_slug = '<canonical-slug>'
ORDER BY ma.source_id, ma.alias_kind;
```

If no canonical row exists but first-party evidence is clear, create one with `canonical_confidence = 'verified'` or `'probable'` and attach exact aliases with provenance. Use `canonical_confidence = 'manual_review'` when identity is ambiguous.

## 5. Fill Launch Gaps from Announcements

Use LLM-assisted extraction only after preserving the raw source text. Insert facts into the schema tables that own them:

- `model`: developer, family, generation, variant, parameter scale, training role, release date, snapshot date, knowledge cutoff, stability, `open_weights`.
- `model_alias`: exact API id, display name, router id, canonical slug, HF repo id, Bedrock id, Vertex id, pricing id, latest alias.
- `provider_surface`: provider, surface type, region, endpoint model id, metadata for hosted API surfaces.
- `model_artifact`: HF repo id or weights URL, artifact type, author, gated status, license, sha, last modified.
- `model_capability`: context window, max output, vision, audio, tool call, reasoning, structured output, image, video, or other source-backed capability values.
- `price_component`: input/output/cache/web-search/image components, source units, raw amount, normalized USD per 1M tokens, tier condition, validity windows.
- `benchmark_result`: benchmark id, score, metric, rank, confidence interval, votes, conditions, measured date, raw row JSON. Set `self_reported = 1` for provider-announcement results.

Do not store benchmark effort or thinking variants as separate `model` rows. Put them in `benchmark_result.eval_condition_json`.

## 6. Recheck Gaps and Queue Ambiguity

- Leave unresolved duplicates in `entity_resolution_queue` with candidate features rather than merging by vibe.
- Mark missing external benchmark sources for a later pass.
- Prefer appending new facts with validity windows over overwriting older rows.
- Keep every alias string observed, even if it looks redundant.
