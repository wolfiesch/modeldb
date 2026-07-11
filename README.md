# ModelDB

[**models.wolfie.gg**](https://models.wolfie.gg) is an inspectable database and analytical dashboard for AI models. It keeps model releases, aliases, benchmark results, prices, provider surfaces, and open-weight artifacts separate, dated, and connected to the source snapshots that supplied them.

The project is for answering questions that a leaderboard alone cannot: Which release does a provider alias mean? Was a benchmark result self-reported? What evaluation conditions came with it? When did a price become valid? What actually changed between two recorded observations?

## Architecture

```text
source documents
  → append-only source snapshots
  → source records + alias resolution
  → canonical SQLite facts with provenance and validity windows
  → static JSON extraction
  → React + ECharts dashboard
```

| Layer | Responsibility |
| --- | --- |
| `ingest/` | Fetches and parses source-specific records. |
| `db/` | Defines the SQLite schema and source registry. |
| `store/` | Resolves identities and promotes facts into the database. |
| `dashboard/scripts/extract.mjs` | Bakes database-backed static JSON for the client. |
| `dashboard/src/` | React, TypeScript, Tailwind, and ECharts analytical views. |
| `viz/` | Standalone chart rendering utilities. |

## What the dashboard covers

| View | Purpose |
| --- | --- |
| Model explorer and detail views | Browse canonical releases and their recorded facts. |
| Benchmarks, ELO, and race views | Compare results while retaining result-level provenance. |
| Price, quality, and latency views | Explore tradeoffs across recorded model facts. |
| Timeline and landscape views | Put releases and capabilities in context. |
| Changes | Inspect model additions, changed benchmark results, price-validity changes, alias first sightings, and source refreshes derived from stored observations. |
| Lineage and identity views | Inspect the distinction between canonical models and source-facing names. |

## Quickstart

Requirements: Python 3, [uv](https://docs.astral.sh/uv/) or pip, and [Bun](https://bun.sh/).

```bash
# Install Python dependencies and initialize the local SQLite database.
uv pip install -r requirements.txt
python3 db/init.py

# Fetch configured sources, resolve identities, and promote facts.
python3 -m store.pipeline

# Install JavaScript dependencies, extract static data, and run the dashboard.
bun install
bun run dash:extract
bun run dash:dev
```

The development server is provided by Vite. To make a production dashboard build:

```bash
bun run dash:build
```

The database and raw source snapshots are intentionally ignored by Git. A local rebuild fetches the sources available at that time; it is not a frozen reproduction of a prior capture.

## Data and provenance methodology

The schema is designed around a few constraints:

- **Raw source payloads are append-only snapshots.** Snapshot records retain URL, fetch time, content hash, and parser version.
- **Canonical identity is separate from source identity.** Source-facing identifiers become aliases and are retained even when unresolved or superseded.
- **Facts carry context.** Benchmark results can retain their source snapshot, measured date, self-reported flag, and evaluation-condition payload. Prices retain source and validity windows.
- **Time is evidence, not decoration.** The Changes feed is derived from persisted timestamps and observations. It omits a category when the stored data cannot support a faithful historical comparison.

Source coverage and resolution quality depend on accessible upstream material. A recorded provider statement is not automatically an independent measurement, and benchmark scores are only meaningful alongside their stated benchmark and recorded conditions.

## Deployment

The public dashboard is a static site. `bun run dash:build` first extracts database data into `dashboard/public/data/`, then builds the Vite application into `dashboard/dist/`.

The production host serves a static directory through Caddy. Deploy the built client while excluding `data/`: the server-side refresh workflow owns the live data directory, and excluding it prevents a stale or incomplete local extraction from overwriting server-generated metrics. Configure `MODELDB_DEPLOY_TARGET` as the SSH destination and remote static path.

```bash
rsync -avz --delete --exclude data/ dashboard/dist/ "$MODELDB_DEPLOY_TARGET"
```

## Further reading

- [`db/schema.sql`](db/schema.sql) - database tables and relationships
- [`db/seed_sources.sql`](db/seed_sources.sql) - source registry
- [`docs/SCHEMA.md`](docs/SCHEMA.md) - schema notes and example queries
- [`docs/SOURCES.md`](docs/SOURCES.md) - source catalog and access notes
- [`docs/REPO.md`](docs/REPO.md) - repository layout and workflow commands
