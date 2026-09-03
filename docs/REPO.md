# modeldb repo guide

This guide explains the repository layout and how to run each layer. The pipeline is live end to end: source parsers ingest into SQLite, `store/` promotes provenance-bearing canonical facts, `dashboard/scripts/extract.mjs` bakes static JSON, and the React dashboard renders it at `models.wolfie.gg`.

## Directory tree

```text
modeldb/
├── db/
│   ├── schema.sql               # canonical tables and indexes
│   ├── seed_sources.sql         # source registry (tiers, auth, cadence, notes)
│   ├── init.py                  # python -m db.init: apply schema + seeds
│   └── modeldb.sqlite           # generated locally, gitignored
├── ingest/
│   ├── base.py                  # SourceParser, SourceModelRecord, snapshot/store plumbing
│   ├── run.py                   # CLI driver + PARSER_SPECS parser registry
│   └── sources/                 # one parser module per source
├── resolve/                     # alias normalization + entity resolution (queue CLI in resolver.py)
├── store/                       # promotion pipeline: pipeline.py, spine.py, prices.py,
│                                # quality_gates.py, launch_registry.py, per-benchmark promoters
├── scripts/
│   ├── vps-refresh.sh           # live refresh entrypoint (systemd ExecStart)
│   ├── collect_omp_tps.py       # paid OMP TPS collection (non-gating enrichment)
│   ├── omp_tps_models.json      # TPS selector config
│   ├── omp_speedtest.py
│   ├── apply_queue_approvals.py # apply reviewed queue approvals with backup + pipeline rerun
│   └── systemd/                 # modeldb-tps-refresh.service + .timer
├── dashboard/
│   ├── scripts/extract.mjs      # bakes DB-backed static JSON into dashboard/public/data/
│   └── src/                     # React 19 + TypeScript + Tailwind + ECharts app
├── viz/                         # standalone bun chart scripts + queries.sql
├── docs/                        # PLAN.md, SCHEMA.md, SOURCES.md, REPO.md
├── tests/                       # pytest suite (temp/fixture DBs only)
├── data/raw/                    # append-only raw snapshots, gitignored
├── package.json                 # dash:extract / dash:dev / dash:build scripts
├── requirements.txt             # pip fallback; canonical deps live in pyproject.toml
└── pyproject.toml               # requires-python >=3.12; pandas, pyarrow, matplotlib
```

## Directory responsibilities

### `db/`

The SQLite spine.

- `schema.sql` defines all canonical tables and indexes.
- `seed_sources.sql` populates the `source` registry with ranked sources, access metadata, cadence, and parser notes.
- `modeldb.sqlite` is generated locally and gitignored.

Agents should treat `db/schema.sql` as the contract for all parser, resolver, and query code. Do not invent columns in docs or code; add schema columns only through an explicit schema change.

### `ingest/`

The deterministic source ingestion layer.

- `base.py` provides `SourceModelRecord` (the pre-resolution record shape), the `SourceParser` subclass interface, `snapshot()`/`store_records()` helpers, and `connect()` (opens `db/modeldb.sqlite` with foreign keys enabled).
- `run.py` drives everything: `PARSER_SPECS` lists every registered source parser; `all` runs each available one except `mteb` and `omp_speedtest`, which are exclude-from-all (live MTEB is HF parquet; OMP speedtest is local/paid).
- Source parsers subclass `SourceParser`, set `source_id` to an exact row from `source`, and emit only source-native records. Parsers must not create canonical `model` rows.

### `resolve/`

The entity-resolution layer.

- `normalize.py` normalizes source-facing names and organizations.
- `resolver.py` resolves records, upserts aliases, queues ambiguous matches in `entity_resolution_queue`, and doubles as the queue-operations CLI (see below).

Resolver invariants: keep aliases even after canonical resolution; store fact provenance through `source_snapshot_id`; ambiguous candidates go to the queue instead of guessing.

### `store/`

The promotion pipeline that turns source records into canonical facts.

`python3 -m store.pipeline` runs, in order: core source ingest → `build_spine` (canonical `model` rows) → launch registry → OpenRouter alias bridging → surfaces, artifacts, prices, capabilities, benchmarks, arena, external benchmarks, Open LLM Leaderboard, MTEB, DeepSWE, FrontierSWE, Artificial Analysis, OMP speedtest, vLLM, and launch-benchmark promotion. `store/quality_gates.py` validates the DB (with an optional pre-run baseline copy) and writes a JSON report consumed by the live refresh.

### `data/raw/`

Append-only raw snapshot storage, written by `SourceParser.snapshot()` under `data/raw/<source>/`. Gitignored because payloads are large and reproducible. Must remain append-only for auditability; parser upgrades create new derived records from preserved raw payloads rather than mutating raw source truth.

### `dashboard/`

React 19 + TypeScript + Tailwind + ECharts static-site app.

- `scripts/extract.mjs` bakes database-backed static JSON into `dashboard/public/data/` (gitignored).
- `src/lib/` holds testable pure modules with colocated `*.test.ts` files run by `bun test`.
- `dashboard/package.json` defines `dev`, `build` (`tsc -b && vite build`), `lint` (oxlint), and `preview`.

### `viz/`

Standalone bun chart/report scripts (`.mjs`) plus `queries.sql`; rendered SVG intermediates under `viz/out/` are gitignored.

### `docs/`

- `PLAN.md`: architecture and milestone plan.
- `SCHEMA.md`: table-level schema guide and SQL examples.
- `SOURCES.md`: ranked source catalog, access notes, and cadence.
- `REPO.md`: this file.

## How to run a layer

Assume a POSIX shell and run from the repository root. Python 3.12+ (`requires-python` in `pyproject.toml`); deps via `uv pip install -r requirements.txt` or pip. JavaScript tooling via [Bun](https://bun.sh/) with two lockfiles: `bun.lock` at the root and `dashboard/bun.lock`.

### 1. Initialize or regenerate the local database

```bash
python3 -m db.init
```

Applies `db/schema.sql` and `db/seed_sources.sql` to `db/modeldb.sqlite` and prints the created tables. The DB file is gitignored.

### 2. Ingest sources

```bash
python3 -m ingest.run models_dev
python3 -m ingest.run openrouter
python3 -m ingest.run all
```

The CLI takes one positional argument: a `source_id` or `all` (see `PARSER_SPECS` in `ingest/run.py` for the full list; `docs/SOURCES.md` documents each source). `all` skips the exclude-from-all parsers (`mteb`, `omp_speedtest`) and prints any registered-but-unavailable parser with its reason. Expected behavior per parser run: `fetch()` → `snapshot()` (writes `data/raw/<source>/` + `source_snapshot` row) → `parse()` → `store_records()` (`source_model_record` rows).

### 3. Run the promotion pipeline

```bash
python3 -m store.pipeline
python3 -m store.pipeline --no-fetch          # reuse existing snapshots
python3 -m store.pipeline --enrich-network    # capped HF + OpenRouter /endpoints enrichment
```

Flags (from `store/pipeline.py` argparse): `--no-fetch` skips source ingest, `--enrich-network` opts into capped network enrichment with `--huggingface-limit` (default 100) and `--openrouter-endpoint-limit` (default 150).

### 4. Work the entity-resolution queue

```bash
python3 -m resolve.resolver queue-report [source_id]
python3 -m resolve.resolver options QUEUE_ID
python3 -m resolve.resolver queue-export [--format csv|markdown] [--suggested-only] [source_id]
python3 -m resolve.resolver queue-candidates-export [--format csv|markdown] [source_id]
python3 -m resolve.resolver accept QUEUE_ID MODEL_ID
python3 -m resolve.resolver accept-batch [--dry-run] FILE.json
python3 -m resolve.resolver accept-new-model-batch [--dry-run] FILE.json
python3 -m resolve.resolver accept-organization-batch [--dry-run] FILE.json
python3 -m resolve.resolver drain-accepted [--dry-run] [--queue-id QUEUE_ID ...]
```

Prefer scoped drains (`--queue-id`) over unscoped queue drains. To apply reviewed approvals and rerun the pipeline safely, `scripts/apply_queue_approvals.py` wraps the batch accepts with a DB backup (`--db`, `--backup-dir`, `--skip-pipeline` flags; positional `approvals_json`).

### 5. Query the database

```bash
sqlite3 db/modeldb.sqlite \
  "SELECT id, name, ingestion_class, auth_type FROM source ORDER BY id;"
```

```bash
sqlite3 db/modeldb.sqlite \
  "SELECT canonical_slug, release_date FROM model ORDER BY release_date DESC LIMIT 20;"
```

For richer examples, see [`docs/SCHEMA.md`](SCHEMA.md#example-queries).

### 6. Dashboard

Root `package.json` scripts (run with `bun run <script>`):

```bash
bun install                                # root deps (root bun.lock)
bun run dash:extract                       # bun dashboard/scripts/extract.mjs
bun run dash:dev                           # Vite dev server for dashboard/
bun run dash:build                         # extract + production build
```

Inside `dashboard/` (own `bun.lock`):

```bash
cd dashboard && bun install
cd dashboard && bun test                   # src/lib *.test.ts + scripts/*.test.mjs
cd dashboard && bun run lint               # oxlint (no lint script exists at the root)
```

`dash:build` requires a populated `db/modeldb.sqlite`; the extract step reads the live DB.

### 7. Tests and quality gates

```bash
python3 -m pytest tests/ -q                 # suite uses temp/fixture DBs, never db/modeldb.sqlite
python3 -m store.quality_gates --db db/modeldb.sqlite --report-file .perf/quality-gates/latest.json
```

`store.quality_gates` also accepts `--baseline <sqlite copy>` to compare against a pre-run snapshot, as the live refresh does.

### 8. Regenerate from scratch

```bash
rm -f db/modeldb.sqlite db/modeldb.sqlite-wal db/modeldb.sqlite-shm
python3 -m db.init
python3 -m store.pipeline
bun run dash:build
```

Raw snapshots under `data/raw/` can be kept; a rebuild re-fetches whatever the sources serve at that time and is not a frozen reproduction of a prior capture.

## Live production refresh (systemd)

`scripts/systemd/` holds the units that refresh the public dashboard on the VPS:

- `modeldb-tps-refresh.timer` — daily at 02:15 America/Los_Angeles (`RandomizedDelaySec=45m`, `Persistent=true`).
- `modeldb-tps-refresh.service` — oneshot unit running as user `wolfie` with `MODELDB_REPO=/srv/modeldb`, `STATIC_DIR=/srv/agent-webhook-hub/static/models`, and paid-TPS env (`OMP_TPS_ALLOW_PAID=1`, `OMP_TPS_RUNS=3`, `OMP_TPS_TIMEOUT=120`). `ExecStart` is `scripts/vps-refresh.sh`.

`scripts/vps-refresh.sh` (`set -euo pipefail`) runs, in order:

1. Copy the current DB to a temp quality baseline.
2. `python3 -m store.pipeline`.
3. `OMP_TPS_ALLOW_PAID=... python3 scripts/collect_omp_tps.py --config scripts/omp_tps_models.json --runs ... --timeout ...` — paid enrichment, deliberately non-gating: on failure it warns and publishes with previously stored TPS samples.
4. `python3 -m store.quality_gates --db db/modeldb.sqlite --baseline ... --report-file .perf/quality-gates/latest.json`.
5. `bun dashboard/scripts/extract.mjs`.
6. `rsync -av --delete dashboard/public/data/ "$STATIC_DIR/data/"`.

Deploying the built client from a local machine is documented in [`README.md`](../README.md#deployment); always exclude `data/` so the server-owned live data directory is not clobbered.

## Agent checklist

Before editing code or docs in this repo:

1. Read `docs/PLAN.md` for architecture and milestones.
2. Read `db/schema.sql` before referencing any table or column.
3. Read `db/seed_sources.sql` before referencing source IDs, auth modes, endpoint URLs, or source notes.
4. Read `ingest/base.py` before adding parser code; register new parsers in `ingest/run.py` `PARSER_SPECS` and `db/seed_sources.sql`.
5. Never run tests or promotions against the live `db/modeldb.sqlite` on the VPS; local tests use temp/fixture DBs.
6. Keep layer boundaries strict: ingest records source truth; resolve builds canonical identity; store promotes facts with provenance; consume queries the DB.
