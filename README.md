# modeldb

`modeldb` is a personal-research LLM intelligence aggregator: a local SQLite database for tracking model releases, aliases, prices, benchmarks, provider surfaces, and open-weight artifacts over time.

It is designed for launch-day curiosity: when a new model appears, ingest the available source data, resolve it against historical aliases, and query the local corpus for comparisons, visualizations, and story angles.

> Personal/education use. Licensing is explicitly out of scope.

## Shape

```text
sources
  → ingest  (fetch → raw append-only snapshot → source_model_record)
  → resolve (aliases → canonical model identity or review queue)
  → store   (SQLite facts with provenance, confidence, validity windows)
  → consume (new-model-drop workflow, notebooks, charts, exports)
```

## Status

**M0 scaffold.** The repo currently contains:

| Area | Status |
|---|---|
| Schema | `db/schema.sql` defines the SQLite spine. |
| Source registry | `db/seed_sources.sql` ranks and describes the source catalog. |
| Ingest base | `ingest/base.py` defines the parser interface and snapshot plumbing. |
| Docs | `docs/PLAN.md`, `docs/SCHEMA.md`, `docs/SOURCES.md`, and `docs/REPO.md`. |

Parser implementations, resolver entrypoints, the `new-model-drop` skill, and visualization/export helpers are milestone work.

## Start here

Read the plan first:

- [`docs/PLAN.md`](docs/PLAN.md) — architecture, locked design decisions, milestones.
- [`docs/SCHEMA.md`](docs/SCHEMA.md) — every table, invariant, and example SQL query.
- [`docs/SOURCES.md`](docs/SOURCES.md) — ranked source catalog and access notes.
- [`docs/REPO.md`](docs/REPO.md) — repo layout and intended layer commands.

## Core invariants

- Raw source payloads are append-only snapshots.
- Canonical model identity is separate from source-specific aliases.
- Aliases are never discarded.
- Prices, capabilities, benchmarks, artifacts, and provider surfaces carry source provenance.
- Effort/thinking benchmark settings are eval conditions, not new models.
- Quantized files are artifact variants, not canonical models.
