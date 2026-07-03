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

## Quickstart

The committed `viz/out/*.png` gallery is viewable as-is. To rebuild the database
and re-render the charts from a fresh clone:

```bash
# 1. Python deps (ingest + resolve + store pipeline)
uv pip install -r requirements.txt    # or: python3 -m pip install -r requirements.txt

# 2. Create the SQLite database from schema + source seed
python3 db/init.py

# 3. Populate it: fetch live sources -> resolve identity -> promote facts
python3 -m store.pipeline           # add --no-fetch to reuse existing raw snapshots

# 4. JS deps + render the charts (writes viz/out/*.png)
bun install
for f in viz/*.mjs; do bun "$f"; done
```

> The DB (`db/modeldb.sqlite`, ~100 MB) and raw snapshots (`data/raw/`) are
> git-ignored because they are regenerable. `store/pipeline.py` fetches live
> sources, so a rebuild reflects source state at run time, not a frozen fixture.

## Dashboard

`dashboard/` is a static React + ECharts SPA for browsing everything in the DB,
live at <https://models.wolfie.gg>.

```bash
bun run dash:dev      # extract-once assumed; Vite dev server at :5173
bun run dash:build    # bake db -> dashboard/public/data/*.json, then vite build -> dashboard/dist/
```

Deploy (Hostinger VPS, Caddy static site):

```bash
bun run dash:build
rsync -avz --delete dashboard/dist/ hostinger-devbox-ts:/srv/static/models/
```

The Caddy route (`models.wolfie.gg` block in `/srv/agent-webhook-hub/Caddyfile`)
serves `/srv/static/models`. Cloudflare DNS is one-time setup; redeploys after a
DB refresh are just the two commands above. Use `hostinger-devbox` instead of
`hostinger-devbox-ts` only when Tailscale is unavailable.

## Status

**M1 working.** Ingest parsers, the resolve/store pipeline, and the
visualization layer are implemented and produce a populated database plus a
rendered chart gallery.

| Area | Status |
|---|---|
| Schema | `db/schema.sql` defines the SQLite spine; `db/init.py` applies it. |
| Source registry | `db/seed_sources.sql` ranks and describes the source catalog. |
| Ingest | `ingest/` parsers for models.dev, OpenRouter, Epoch, LMArena, and more. |
| Pipeline | `store/pipeline.py` runs ingest → spine → bridge → promote facts. |
| Visualization | `viz/` shared lib + 8 charts (frontier, elo_over_time, model_landing, plus 5 Sonnet 5 launch visuals: spec_card, price_ladder, cache_economics, knowledge_freshness, lineage_elo, all comparing a curated peer cohort via `viz/lib/peers.mjs`); 7-tool bake-off in `viz/bakeoff/`. |
| Skill | `.claude/skills/new-model-drop/` research + viz workflow. |
| Docs | `docs/PLAN.md`, `docs/SCHEMA.md`, `docs/SOURCES.md`, `docs/REPO.md`. |

## Start here

Read the plan first:

- [`docs/PLAN.md`](docs/PLAN.md): architecture, locked design decisions, milestones.
- [`docs/SCHEMA.md`](docs/SCHEMA.md): every table, invariant, and example SQL query.
- [`docs/SOURCES.md`](docs/SOURCES.md): ranked source catalog and access notes.
- [`docs/REPO.md`](docs/REPO.md): repo layout and intended layer commands.

## Core invariants

- Raw source payloads are append-only snapshots.
- Canonical model identity is separate from source-specific aliases.
- Aliases are never discarded.
- Prices, capabilities, benchmarks, artifacts, and provider surfaces carry source provenance.
- Effort/thinking benchmark settings are eval conditions, not new models.
- Quantized files are artifact variants, not canonical models.
