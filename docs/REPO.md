# modeldb repo guide

This guide explains the repository layout and how an agent should run each layer described in [`docs/PLAN.md`](PLAN.md). The current status is **M0 scaffold**: the schema, source registry, parser interface, and reference docs exist; parsers and resolver modules are still milestone work.

## Directory tree

```text
modeldb/
├── README.md
├── .gitignore
├── db/
│   ├── schema.sql
│   ├── seed_sources.sql
│   └── modeldb.sqlite          # generated locally, gitignored
├── ingest/
│   ├── base.py                 # SourceParser, SourceModelRecord, snapshot/store plumbing
│   ├── registry.py             # planned parser registry
│   ├── run.py                  # planned ingest driver
│   └── sources/                # planned one parser module per source
├── resolve/                    # planned alias normalization and entity resolution layer
├── data/
│   └── raw/                    # generated append-only raw snapshots, gitignored
├── docs/
│   ├── PLAN.md
│   ├── SCHEMA.md
│   ├── SOURCES.md
│   └── REPO.md
├── viz/                        # planned notebooks and export helpers
└── .claude/
    └── skills/
        └── new-model-drop/     # planned recurring workflow skill
```

Only `db/`, `docs/`, and `ingest/base.py` are present in the M0 scaffold. Planned directories are listed because the architecture in `docs/PLAN.md` already reserves them.

## Directory responsibilities

### `db/`

The SQLite spine.

- `schema.sql` defines all canonical tables and indexes.
- `seed_sources.sql` populates the `source` registry with ranked sources, access metadata, and parser notes.
- `modeldb.sqlite` is generated locally and gitignored.

Agents should treat `db/schema.sql` as the contract for all parser, resolver, and query code. Do not invent columns in docs or code; add schema columns only through an explicit schema change.

### `ingest/`

The deterministic source ingestion layer.

- `base.py` provides:
  - `SourceModelRecord`: the pre-resolution record shape.
  - `SourceParser`: the subclass interface for each source.
  - `snapshot()`: writes raw bytes and inserts `source_snapshot` rows.
  - `store_records()`: inserts `source_model_record` rows.
  - `run()`: `fetch → snapshot → parse → store`.
  - `connect()`: opens the local SQLite DB with foreign keys enabled.
- Future source parsers should subclass `SourceParser`, set `source_id` to an exact row from `source`, and emit only source-native records. Parsers must not create canonical `model` rows.

### `resolve/`

The entity-resolution layer planned by `docs/PLAN.md`.

Responsibilities:
- Normalize aliases.
- Bridge by high-confidence evidence such as HF repo IDs, provider docs, source canonical slugs, and exact provider IDs.
- Attach aliases to `model`, `provider_surface`, or `model_artifact` rows.
- Queue ambiguous matches in `entity_resolution_queue`.

### `data/raw/`

Append-only raw snapshot storage.

- Written by `SourceParser.snapshot()` under `data/raw/<source>/`.
- Gitignored because payloads may be large and are reproducible.
- Must remain append-only for auditability; parser upgrades should create new derived records from preserved raw payloads rather than mutating the raw source truth.

### `docs/`

Reference documentation.

- `PLAN.md`: architecture and milestone plan.
- `SCHEMA.md`: table-level schema guide and SQL examples.
- `SOURCES.md`: ranked source catalog and access notes.
- `REPO.md`: this file.

### `viz/`

Planned consume/export layer.

Expected use:
- Local notebooks.
- SQLite queries for charts.
- Export helpers for story angles and public visualizations.

### `.claude/skills/new-model-drop/`

Planned recurring workflow skill.

Expected use:
- Research a named model release.
- Run targeted source ingestion.
- Resolve or queue identity matches.
- Produce query-backed story angles.

## How to run a layer

The commands below are illustrative for the M0 scaffold. They show the intended layer boundaries; parser modules and resolver entrypoints are milestone work.
Assume a POSIX shell (`sh`, `bash`, or `zsh`) and run examples from the repository root.

### 1. Initialize or regenerate the local database

```bash
sqlite3 db/modeldb.sqlite < db/schema.sql
sqlite3 db/modeldb.sqlite < db/seed_sources.sql
```

This creates the local SQLite spine and loads the source registry. The generated DB file is gitignored.

### 2. Ingest one source

Planned shape:

```bash
uv run python -m ingest.run models_dev
uv run python -m ingest.run openrouter
```

Expected behavior for a parser run:

1. `fetch()` returns `(url, raw_bytes, http_meta)`.
2. `snapshot()` writes `data/raw/<source>/...raw` and inserts `source_snapshot`.
3. `parse()` yields `SourceModelRecord` rows.
4. `store_records()` inserts `source_model_record` rows.

Parser contract:
- Source parsers emit source-native IDs and parsed fields only.
- Parsers never write canonical `model` rows.
- Parser `source_id` must match a row in `source`.

### 3. Run resolver

Planned shape:

```bash
uv run python -m resolve.run --source models_dev
uv run python -m resolve.run --all
```

Expected resolver behavior:

1. Read unresolved `source_model_record` rows.
2. Create or update `model_alias` rows for exact source strings.
3. Bridge aliases to canonical `model` rows through confidence-ranked evidence.
4. Create `provider_surface`, `model_artifact`, `price_component`, `model_capability`, and `benchmark_result` facts as supported by parsed fields.
5. Insert ambiguous candidates into `entity_resolution_queue` instead of guessing.

Resolver invariants:
- Keep aliases even after canonical resolution.
- Store fact provenance through `source_snapshot_id`.
- Use `benchmark_result.eval_condition_json` for effort/thinking settings.
- Use `artifact_variant` for quantization and file variants.

### 4. Query the database

Example direct SQLite queries:

```bash
sqlite3 db/modeldb.sqlite \
  "SELECT id, name, ingestion_class, auth_type FROM source ORDER BY id;"
```

```bash
sqlite3 db/modeldb.sqlite \
  "SELECT canonical_slug, release_date FROM model ORDER BY release_date DESC LIMIT 20;"
```

For richer examples, see [`docs/SCHEMA.md`](SCHEMA.md#example-queries).

### 5. Regenerate from scratch

Because raw snapshots and the local DB are generated artifacts, the intended rebuild flow is to remove only the generated SQLite files, then reload schema and seeds:

```bash
rm -f db/modeldb.sqlite db/modeldb.sqlite-wal db/modeldb.sqlite-shm
sqlite3 db/modeldb.sqlite < db/schema.sql
sqlite3 db/modeldb.sqlite < db/seed_sources.sql
uv run python -m ingest.run models_dev
uv run python -m resolve.run --all
```

In M0, the final ingest and resolve commands are placeholders for the milestone entrypoints.

## Agent checklist

Before editing code or docs in this repo:

1. Read `docs/PLAN.md` for architecture and milestones.
2. Read `db/schema.sql` before referencing any table or column.
3. Read `db/seed_sources.sql` before referencing source IDs, auth modes, endpoint URLs, or source notes.
4. Read `ingest/base.py` before adding parser code.
5. Keep layer boundaries strict: ingest records source truth; resolve builds canonical identity; store keeps provenance; consume queries the DB.
