# modeldb — LLM Model Intelligence Aggregator

Personal research project. Aggregate everything-we-can-find about every generally-available
LLM into one local SQLite database, so that on launch day a new model is just an incremental
add against a rich historical corpus — then splice/correlate/visualize for fun (and Twitter).

> Personal/education use. Licensing is explicitly out of scope.

## The shape of it

```
                    ┌─────────────────────────────────────────────┐
   SOURCES          │              INGEST (deterministic)          │
  (recon'd) ──────► │  fetch → snapshot (raw, append-only) → parse │
                    │       → emit source_model_record rows        │
                    └───────────────────┬─────────────────────────┘
                                        │
                                        ▼
                    ┌─────────────────────────────────────────────┐
                    │           RESOLVE (entity resolution)        │
                    │  normalize alias → bridge by HF id / slug /  │
                    │  provider-doc → merge into canonical model   │
                    │  or queue ambiguous for review               │
                    └───────────────────┬─────────────────────────┘
                                        │
                                        ▼
                    ┌─────────────────────────────────────────────┐
                    │        SQLite spine (db/schema.sql)          │
                    │  model · alias · price · benchmark · cap ·   │
                    │  provider_surface · artifact · snapshot      │
                    └───────────────────┬─────────────────────────┘
                                        │
                          ┌─────────────┴─────────────┐
                          ▼                           ▼
                ┌──────────────────┐        ┌────────────────────┐
                │  new-model-drop  │        │   VIZ / EXPORT     │
                │  skill (research │        │  notebooks, charts,│
                │  + incremental   │        │  story angles for  │
                │  add + story)    │        │  Twitter           │
                └──────────────────┘        └────────────────────┘
```

Four layers, each independently runnable and agent-managed:

1. **Ingest** — one deterministic parser per source. Each fetches, writes the raw body to
   `data/raw/<source>/`, records a `source_snapshot`, and emits normalized
   `source_model_record` rows. Parsers never invent canonical IDs.
2. **Resolve** — turns source records into aliases and merges them onto canonical `model`
   rows using a confidence ladder. Ambiguous cases go to `entity_resolution_queue`.
3. **Store** — the SQLite spine. Append-only snapshots + provenance on every fact. See
   `docs/SCHEMA.md`.
4. **Consume** — the `new-model-drop` skill and visualization/export notebooks.

## Design decisions (locked)

- **SQLite is the spine.** Single file, queryable, diffable-enough, zero infra.
- **Own canonical slug**, models.dev IDs are aliases — avoids lock-in.
  Format: `{developer}/{family}-{variant}[@{snapshot}]` e.g. `anthropic/claude-sonnet-4.5@2025-09-29`.
- **Aliases are never discarded.** Every source string is preserved with provenance.
- **Effort/thinking variants** (`gpt-5-high`, `claude-…-thinking`) are an `eval_condition` on
  benchmark rows, not separate canonical models.
- **Quantizations/forks** are `artifact_variant` / `derived_model`, not new base models.
- **Self-reported benchmarks** (announcement tables) are flagged `self_reported=1` and kept
  separate from independent aggregator numbers.
- **Raw first, parse second.** Always persist the raw payload; parsers can be re-run/upgraded.
- **Prices stored raw + normalized** to `usd_per_1m_tokens` (sources disagree on units:
  OpenRouter per-token strings, models.dev $/Mtok, Portkey cents/token).

## Source priority (full ranking in docs/SOURCES.md)

**Tier 1 — build first (clean, official, high coverage):**
`models.dev` (spine) · `OpenRouter` (routing+price+HF bridge) · `Epoch AI` (benchmark ZIP) ·
`LMArena HF parquet` (ELO) · `LiteLLM` (alias explosion) · `simonw/llm-prices` (price history)

**Tier 2 — high value, auth or normalization:**
`Artificial Analysis` (free API key) · `Hugging Face Hub` (open-weight identity) ·
`SWE-bench` · `Aider polyglot` · `LiveBench` · `Open LLM LB (archived)` ·
provider APIs (Anthropic/OpenAI/Gemini/Mistral)

**Tier 3 — extraction-heavy / fragile:**
HF model cards · provider announcements (LLM-assisted) · Scale SEAL (scrape) · LLM Stats

## Milestones

- **M0 Scaffold** *(this commit)* — repo, schema, source registry, parser interface, skill stub.
- **M1 Spine** — implement `models.dev` + `OpenRouter` parsers + resolver bridge by `hugging_face_id`.
  Goal: a populated `model` table with prices + context for every routable model.
- **M2 Benchmarks** — Epoch ZIP + LMArena parquet + SWE-bench + Aider. Goal: rich benchmark coverage.
- **M3 Enrichment** — Artificial Analysis (key), HF Hub for open weights, provider APIs.
- **M4 Skill loop** — `new-model-drop` end-to-end: research a named model, incremental add, story angles.
- **M5 Viz** — notebooks + export for the recurring Twitter content.

## Repo layout

See `docs/REPO.md`. Top level:
```
db/          schema.sql, seed_sources.sql, modeldb.sqlite (gitignored)
ingest/      one parser per source + base.py interface + registry
resolve/     normalization + entity resolution
data/raw/    append-only raw snapshots (gitignored)
docs/        PLAN.md (this), SCHEMA.md, SOURCES.md, REPO.md
viz/         analysis notebooks + export helpers
.claude/skills/new-model-drop/   the recurring workflow
```
