-- modeldb canonical schema
-- SQLite is the spine. Design principles:
--   1. Append-only raw snapshots: never lose what a source actually returned.
--   2. Canonical model identity is separate from source-specific aliases.
--   3. Facts (price, benchmark, capability) carry provenance + confidence + validity window.
--   4. Provider serving surfaces and open-weight artifacts are distinct from the abstract model.
-- See docs/SCHEMA.md for the rationale and entity-resolution workflow.

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ---------------------------------------------------------------------------
-- Source registry + append-only raw snapshots
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source (
  id              TEXT PRIMARY KEY,              -- 'models_dev', 'openrouter', 'lmarena', 'epoch', ...
  name            TEXT NOT NULL,
  base_url        TEXT,
  ingestion_class TEXT CHECK (ingestion_class IN ('A','B','C','D')),
  auth_type       TEXT,                          -- 'none','api_key','bearer'
  update_cadence  TEXT,
  notes           TEXT
);

CREATE TABLE IF NOT EXISTS source_snapshot (
  id             INTEGER PRIMARY KEY,
  source_id      TEXT NOT NULL REFERENCES source(id),
  url            TEXT NOT NULL,
  fetched_at     TEXT NOT NULL,                  -- ISO8601 UTC
  content_hash   TEXT NOT NULL,                  -- sha256 of raw body
  etag           TEXT,
  last_modified  TEXT,
  parser_version TEXT NOT NULL,
  raw_path       TEXT,                           -- path under data/raw/<source>/<ts>.<ext>
  UNIQUE (source_id, url, content_hash)
);

-- ---------------------------------------------------------------------------
-- Canonical identity
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS organization (
  id           TEXT PRIMARY KEY,                 -- 'anthropic','openai','meta','google',...
  display_name TEXT NOT NULL,
  country      TEXT,
  aliases_json TEXT                              -- ['x-ai','xai'] etc.
);

-- An abstract model RELEASE, independent of provider surface or quantization.
-- canonical_slug format: {developer}/{family}-{variant}[@{snapshot}]
--   e.g. anthropic/claude-sonnet-4.5@2025-09-29
CREATE TABLE IF NOT EXISTS model (
  id                  INTEGER PRIMARY KEY,
  canonical_slug      TEXT UNIQUE NOT NULL,
  developer_id        TEXT REFERENCES organization(id),
  family              TEXT,                       -- 'claude','gpt','llama','gemini'
  generation          TEXT,                       -- '4.5','5','3.1' (text, not float)
  tier_or_variant     TEXT,                       -- 'sonnet','opus','flash','maverick'
  parameter_scale     TEXT,                       -- '405b','17b','128e' when known
  training_role       TEXT,                       -- 'base','instruct','chat','reasoning'
  release_date        TEXT,
  snapshot_date       TEXT,
  knowledge_cutoff    TEXT,
  stability           TEXT,                       -- 'pinned','latest_alias','preview','deprecated','retired'
  open_weights        INTEGER,                    -- 0/1/NULL
  display_name        TEXT,                       -- reviewed/public display name when slug derivation is lossy
  canonical_confidence TEXT,                      -- 'verified','probable','manual_review'
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_identity
  ON model (developer_id, family, generation, tier_or_variant, snapshot_date);

-- ---------------------------------------------------------------------------
-- Aliases + entity resolution
-- ---------------------------------------------------------------------------

-- Every source-specific identifier string becomes an alias row. Never discarded.
CREATE TABLE IF NOT EXISTS model_alias (
  id                 INTEGER PRIMARY KEY,
  source_id          TEXT NOT NULL REFERENCES source(id),
  alias_string       TEXT NOT NULL,              -- raw, exact
  alias_normalized   TEXT NOT NULL,
  alias_kind         TEXT NOT NULL,              -- 'api_model_id','display_name','router_id','canonical_slug','hf_repo_id','bedrock_id','vertex_id','pricing_id','arena_model','latest_alias'
  model_id           INTEGER REFERENCES model(id),      -- nullable until resolved
  provider_surface_id INTEGER REFERENCES provider_surface(id),
  artifact_id        INTEGER REFERENCES model_artifact(id),
  valid_from         TEXT,
  valid_to           TEXT,
  resolution_method  TEXT,                        -- 'exact_provider_doc','hf_id_bridge','canonical_slug_bridge','source_base_model','normalized_match','manual_override'
  confidence         REAL NOT NULL DEFAULT 0,
  source_snapshot_id INTEGER REFERENCES source_snapshot(id),
  first_seen_at      TEXT NOT NULL,
  last_seen_at       TEXT NOT NULL
  -- uniqueness incl. nullable valid_from handled by idx_alias_unique below
);

-- SQLite forbids expressions in table UNIQUE constraints; use a unique index.
CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_unique
  ON model_alias (source_id, alias_string, alias_kind, COALESCE(valid_from, ''));

CREATE INDEX IF NOT EXISTS idx_alias_normalized ON model_alias (alias_normalized);
CREATE INDEX IF NOT EXISTS idx_alias_model ON model_alias (model_id);

-- Tracks moving aliases ('latest','chat-latest') across time.
CREATE TABLE IF NOT EXISTS alias_history (
  id                  INTEGER PRIMARY KEY,
  alias_id            INTEGER NOT NULL REFERENCES model_alias(id),
  model_id            INTEGER NOT NULL REFERENCES model(id),
  observed_from       TEXT NOT NULL,
  observed_to         TEXT,
  evidence_snapshot_id INTEGER REFERENCES source_snapshot(id),
  confidence          REAL NOT NULL
);

-- Ambiguous matches a future agent / human must approve.
CREATE TABLE IF NOT EXISTS entity_resolution_queue (
  id               INTEGER PRIMARY KEY,
  source_record_id INTEGER REFERENCES source_model_record(id),
  candidate_model_id INTEGER REFERENCES model(id),
  reason           TEXT NOT NULL,
  features_json    TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'pending', -- 'pending','accepted','rejected'
  created_at       TEXT NOT NULL,
  resolved_at      TEXT
);

CREATE TABLE IF NOT EXISTS entity_resolution_audit (
  id                 INTEGER PRIMARY KEY,
  queue_id           INTEGER NOT NULL REFERENCES entity_resolution_queue(id),
  source_record_id   INTEGER REFERENCES source_model_record(id),
  candidate_model_id INTEGER REFERENCES model(id),
  action             TEXT NOT NULL, -- 'accept','drain'
  details_json       TEXT NOT NULL,
  created_at         TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Raw per-source records (one row per model as that source sees it)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS source_model_record (
  id                 INTEGER PRIMARY KEY,
  source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshot(id),
  source_model_id    TEXT NOT NULL,
  display_name       TEXT,
  provider_name      TEXT,
  raw_record_json    TEXT NOT NULL,
  parsed_fields_json TEXT,
  model_alias_id     INTEGER REFERENCES model_alias(id),
  UNIQUE (source_snapshot_id, source_model_id)
);

-- ---------------------------------------------------------------------------
-- Provider serving surfaces + open-weight artifacts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS provider_surface (
  id                 INTEGER PRIMARY KEY,
  provider_id        TEXT NOT NULL,              -- 'anthropic','amazon-bedrock','google-vertex','openrouter'
  surface_type       TEXT,                       -- 'first_party','openrouter','bedrock','vertex','azure','groq','together'
  region             TEXT,
  endpoint_model_id  TEXT NOT NULL,
  model_id           INTEGER REFERENCES model(id),
  source_snapshot_id INTEGER REFERENCES source_snapshot(id),
  metadata_json      TEXT,
  UNIQUE (provider_id, surface_type, region, endpoint_model_id)
);

CREATE INDEX IF NOT EXISTS idx_surface_endpoint ON provider_surface (endpoint_model_id);

CREATE TABLE IF NOT EXISTS model_artifact (
  id            INTEGER PRIMARY KEY,
  model_id      INTEGER REFERENCES model(id),
  source_id     TEXT REFERENCES source(id),
  artifact_ref  TEXT NOT NULL,                   -- HF repo id e.g. 'meta-llama/Llama-4-Maverick-17B-128E-Instruct'
  artifact_type TEXT,                            -- 'hf_repo','file_set','weights_url'
  author        TEXT,
  gated         TEXT,
  license       TEXT,
  sha           TEXT,
  last_modified TEXT,
  metadata_json TEXT,
  UNIQUE (source_id, artifact_ref)
);

CREATE TABLE IF NOT EXISTS artifact_variant (
  id              INTEGER PRIMARY KEY,
  artifact_id     INTEGER REFERENCES model_artifact(id),
  quantization    TEXT,                           -- 'fp8','gguf:q4_k_m','awq'
  format          TEXT,
  parameter_count INTEGER,
  file_pattern    TEXT,
  metadata_json   TEXT
);

-- ---------------------------------------------------------------------------
-- Facts: capability, price, benchmark
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_capability (
  model_id           INTEGER NOT NULL REFERENCES model(id),
  capability         TEXT NOT NULL,              -- 'context_window','vision','tool_call','reasoning','max_output'
  value              TEXT NOT NULL,
  source_snapshot_id INTEGER REFERENCES source_snapshot(id),
  confidence         REAL,
  PRIMARY KEY (model_id, capability, source_snapshot_id)
);

CREATE TABLE IF NOT EXISTS price_component (
  id                  INTEGER PRIMARY KEY,
  model_id            INTEGER REFERENCES model(id),
  provider_surface_id INTEGER REFERENCES provider_surface(id),
  source_id           TEXT REFERENCES source(id),
  component           TEXT NOT NULL,             -- 'input_token','output_token','cache_read','cache_write','web_search','image'
  unit                TEXT NOT NULL,             -- 'token','1m_tokens','request','second','image'
  currency            TEXT NOT NULL DEFAULT 'USD',
  amount              REAL NOT NULL,             -- raw amount in source units
  normalized_usd_per_1m_tokens REAL,             -- normalized for token components
  tier_condition_json TEXT,                      -- e.g. {">":128000} context-threshold tiers
  valid_from          TEXT,
  valid_to            TEXT,
  source_snapshot_id  INTEGER REFERENCES source_snapshot(id)
);

-- Every source snapshot that independently observed a coalesced price fact.
CREATE TABLE IF NOT EXISTS price_component_observation (
  price_component_id INTEGER NOT NULL REFERENCES price_component(id) ON DELETE CASCADE,
  source_snapshot_id INTEGER NOT NULL REFERENCES source_snapshot(id),
  PRIMARY KEY (price_component_id, source_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_price_lookup
  ON price_component (model_id, provider_surface_id, component, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_price_surface
  ON price_component (provider_surface_id);

CREATE TABLE IF NOT EXISTS benchmark (
  id             TEXT PRIMARY KEY,               -- 'gpqa_diamond','mmlu_pro','swe_bench_verified','lmarena_text_overall'
  name           TEXT NOT NULL,
  category       TEXT,                           -- 'coding','math','reasoning','agentic','arena_elo'
  metric_default TEXT,                           -- 'pass@1','accuracy','elo','percent_resolved'
  higher_is_better INTEGER DEFAULT 1,
  source_url     TEXT
);

CREATE TABLE IF NOT EXISTS benchmark_result (
  id                  INTEGER PRIMARY KEY,
  model_id            INTEGER REFERENCES model(id),
  provider_surface_id INTEGER REFERENCES provider_surface(id),
  benchmark_id        TEXT REFERENCES benchmark(id),
  score               REAL,
  metric              TEXT,
  rank                INTEGER,
  ci                  REAL,                       -- confidence interval half-width
  votes               INTEGER,
  eval_condition_json TEXT,                       -- {effort:'high', thinking:true, category:'coding'}
  self_reported       INTEGER DEFAULT 0,          -- 1 = provider-reported (announcement), 0 = independent
  measured_at         TEXT,
  source_snapshot_id  INTEGER REFERENCES source_snapshot(id),
  raw_record_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_bench_lookup
  ON benchmark_result (model_id, benchmark_id, measured_at);
