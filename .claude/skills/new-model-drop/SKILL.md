---
name: new-model-drop
description: This skill should be used when the user says a new model dropped, names a freshly released LLM, asks "new model drop <name>", wants to add a just-announced model to modeldb, or asks for Twitter-ready analysis and visualization angles for a newly launched model.
version: 0.1.0
---

# New Model Drop Skill

Turn a freshly released model into a repeatable research, ingest, resolution, and visualization loop. Start from a model name or announcement link, preserve raw evidence, add the model incrementally to the SQLite spine, then query the existing corpus for story angles worth charting.

## What It Does

Run the modeldb launch-day workflow end to end:

1. **Research** — Gather independent and first-party evidence for the named model from the known source registry: `models_dev`, `openrouter`, provider announcements, Hugging Face model cards, Artificial Analysis, LMArena, SWE-bench, Aider, Epoch, and related benchmark sources once present. Parallelize source lookups when possible.
2. **Incremental add** — Run only the relevant ingest parsers, resolve aliases onto a canonical `model` row, and fill any launch-day gaps with provenance-backed facts in `model`, `model_alias`, `model_capability`, `provider_surface`, `model_artifact`, `price_component`, and `benchmark_result`.
3. **Story angles** — Compare the new model against historical corpus rows and propose Twitter-ready visualizations: frontier plots, ELO movement, context-window races, cost-per-score charts, open-versus-closed comparisons, and speed-versus-quality scatter plots.

Keep the loop evidence-first. Raw payloads and announcement text matter because parsers and extraction prompts will improve over time.

## Usage

Use when the prompt is launch-day oriented:

```text
new model drop Claude Sonnet 4.5
A new OpenAI model launched; add it and find chart angles
Where does Qwen3-Coder land versus other coding models?
Research this provider blog post and update modeldb
```

Preferred inputs:

- Model name, provider, or API id.
- Announcement URL if available.
- Hugging Face repo id for open-weight models.
- Provider docs URL for pricing or context-window claims.

If only a model name is provided, infer likely providers and search the registry sources first. Do not wait for every benchmark source to update before adding the model; record what exists now, mark missing sources, and allow later snapshots to enrich the same canonical row.

## Architecture

```text
User names model
      │
      ▼
1. RESEARCH
   ├── models.dev / OpenRouter / LiteLLM / llm-prices
   ├── provider docs and launch blog
   ├── HF model card and Hub metadata when open weights exist
   ├── Artificial Analysis / LMArena / SWE-bench / Aider once present
   └── raw evidence + source provenance
      │
      ▼
2. INCREMENTAL ADD
   ├── python -m ingest.run <source_id>
   ├── resolver merges aliases into canonical model rows
   ├── manual or LLM-assisted extraction fills launch facts
   └── verify canonical row, aliases, prices, capabilities, benchmarks
      │
      ▼
3. STORY ANGLES
   ├── run viz/queries.sql or targeted SQL
   ├── export CSV/dataframe for charts
   ├── compare against peer families and frontier models
   └── propose concise Twitter-ready visualization narratives
```

The four project layers are fixed by `docs/PLAN.md`: ingest, resolve, store, consume. Parsers never create canonical models directly; they only persist raw snapshots and `source_model_record` rows. Resolution owns canonical identity and alias attachment. Visualization queries consume the SQLite spine.

## Rules (Detailed Guidance)

Load the matching rule file for the phase being executed:

- [rules/research.md](rules/research.md) — Launch-day research checklist, source order, provenance capture, and self-reported benchmark handling.
- [rules/incremental-add.md](rules/incremental-add.md) — Exact add/update sequence, parser commands, resolver pass, canonical row verification, and manual extraction destinations.
- [rules/story-angles.md](rules/story-angles.md) — Visualization and correlation ideas with the schema columns needed for each.

## When to Use

**Good fit:**

- A newly released model needs to be added to modeldb.
- A provider announcement should be converted into structured facts.
- A named model needs source-backed pricing, context, modality, artifact, and benchmark rows.
- A launch should become a set of interesting comparison charts for Twitter.
- A model exists in one source but has not yet been reconciled across aliases.

**Use narrower tools instead when:**

- Only a static schema question is being asked; inspect `db/schema.sql` directly.
- Only a parser implementation is requested; use the ingest parser conventions and keep to that source.
- Only a chart needs to be rendered from existing data; start from `viz/queries.sql`.

## Anti-Patterns

- **Do not treat provider announcement scores as independent benchmarks.** Insert them as `benchmark_result.self_reported = 1` and preserve the announcement snapshot.
- **Do not invent canonical ids inside parser code.** Emit source-native records and let the resolver decide.
- **Do not discard aliases.** Preserve exact API ids, router ids, display names, Hugging Face repo ids, and latest aliases in `model_alias`.
- **Do not overwrite history.** Use source snapshots and validity windows rather than mutating past facts away.
- **Do not wait for all sources to agree.** Add the model with confidence and provenance now, then enrich as benchmark/aggregator snapshots arrive.
- **Do not mix effort or thinking settings into canonical model identity.** Store evaluation variants in `benchmark_result.eval_condition_json`.
- **Do not chart without checking source meaning.** Compare only compatible benchmark metrics or clearly label mixed proxies.

## Output Shape

For a completed launch-day pass, report:

- Canonical model slug and confidence.
- Source snapshots checked and whether the model appeared.
- Alias strings attached or queued for review.
- Facts inserted or updated by table.
- Missing sources to revisit later.
- 3-5 chart/story angles with the query or columns needed.
