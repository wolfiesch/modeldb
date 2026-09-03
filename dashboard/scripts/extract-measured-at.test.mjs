// Focused regression test: NULL measured_at rows must not lose "latest row"
// picks or sort as oldest. The script orders/windows on the coalesced
// effective date COALESCE(br.measured_at, ss.fetched_at, m.release_date) and
// never bakes "null" dateKeys or NaN timestamps. Runs extract.mjs against a
// fixture DB via MODELDB_EXTRACT_DB / MODELDB_EXTRACT_OUT — the live
// db/modeldb.sqlite and dashboard/public/data are never touched.
import { describe, expect, test } from 'bun:test'
import { Database } from 'bun:sqlite'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

const scriptsDir = import.meta.dir
const EXTRACT = resolve(scriptsDir, 'extract.mjs')

function buildFixture(dbPath) {
 const db = new Database(dbPath)
 db.run(`CREATE TABLE model (
    id INTEGER PRIMARY KEY, canonical_slug TEXT, developer_id TEXT, family TEXT,
    generation TEXT, tier_or_variant TEXT, parameter_scale TEXT, training_role TEXT,
    release_date TEXT, snapshot_date TEXT, knowledge_cutoff TEXT, stability TEXT,
    open_weights INTEGER, canonical_confidence TEXT, created_at TEXT, updated_at TEXT)`)
 db.run(`CREATE TABLE organization (id TEXT PRIMARY KEY, display_name TEXT)`)
 db.run(`CREATE TABLE source (id TEXT PRIMARY KEY, name TEXT)`)
 db.run(`CREATE TABLE source_snapshot (
    id INTEGER PRIMARY KEY, source_id TEXT, url TEXT, fetched_at TEXT,
    content_hash TEXT, etag TEXT, last_modified TEXT, parser_version TEXT, raw_path TEXT)`)
 db.run(`CREATE TABLE benchmark (
    id TEXT PRIMARY KEY, name TEXT, category TEXT, metric_default TEXT,
    higher_is_better INTEGER, source_url TEXT)`)
 db.run(`CREATE TABLE benchmark_result (
    id INTEGER PRIMARY KEY, model_id INTEGER, provider_surface_id INTEGER,
    benchmark_id TEXT, score REAL, metric TEXT, rank INTEGER, ci TEXT, votes INTEGER,
    eval_condition_json TEXT, self_reported INTEGER, measured_at TEXT,
    source_snapshot_id INTEGER, raw_record_json TEXT)`)
 db.run(`CREATE TABLE model_capability (
    model_id INTEGER, capability TEXT, value TEXT, confidence TEXT,
    source_snapshot_id INTEGER)`)
 db.run(`CREATE TABLE price_component (
    id INTEGER PRIMARY KEY, model_id INTEGER, provider_surface_id INTEGER,
    component TEXT, unit TEXT, amount REAL, normalized_usd_per_1m_tokens REAL,
    source_id TEXT, source_snapshot_id INTEGER, valid_from TEXT, valid_to TEXT,
    tier_condition_json TEXT)`)
 db.run(`CREATE TABLE model_alias (
    id INTEGER PRIMARY KEY, model_id INTEGER, source_id TEXT, alias_string TEXT,
    alias_kind TEXT, resolution_method TEXT, confidence TEXT, first_seen_at TEXT,
    last_seen_at TEXT, source_snapshot_id INTEGER)`)
 db.run(`CREATE TABLE provider_surface (
    id INTEGER PRIMARY KEY, model_id INTEGER, provider_id TEXT, surface_type TEXT,
    region TEXT, endpoint_model_id TEXT, metadata_json TEXT, source_snapshot_id INTEGER)`)
 db.run(`CREATE TABLE model_artifact (
    id INTEGER PRIMARY KEY, model_id INTEGER, source_id TEXT, artifact_ref TEXT,
    artifact_type TEXT, author TEXT, gated INTEGER, license TEXT, sha TEXT,
    last_modified TEXT)`)
 db.run(`CREATE TABLE artifact_variant (
    id INTEGER PRIMARY KEY, artifact_id INTEGER, quantization TEXT, format TEXT,
    parameter_count TEXT, file_pattern TEXT, metadata_json TEXT)`)

 db.run(`INSERT INTO source VALUES ('fixture', 'Fixture Source')`)
 // Old snapshot vs newest snapshot with a NULL-measured FrontierSWE-style row.
 db.run(`INSERT INTO source_snapshot VALUES (1, 'fixture', 'https://example.test/old', '2024-05-01T00:00:00+00:00', NULL, NULL, NULL, NULL, NULL)`)
 db.run(`INSERT INTO source_snapshot VALUES (2, 'fixture', 'https://example.test/new', '2026-09-03T03:46:57+00:00', NULL, NULL, NULL, NULL, NULL)`)

 db.run(`INSERT INTO model (id, canonical_slug, release_date) VALUES
    (1, 'fixture/new-model', '2026-08-01'),
    (2, 'fixture/dated-model', '2026-01-01'),
    (3, 'fixture/undatable-model', NULL)`)

 const benchCategories = { fixture_coding: 'coding' }
 for (const id of ['fixture_bench', 'hle', 'lmarena_text_overall', 'lmarena_text_coding', 'fixture_coding']) {
  db.run(`INSERT INTO benchmark VALUES (?, ?, ?, 'score', 1, NULL)`, [id, id, benchCategories[id] ?? 'reasoning'])
 }

 const insertResult = db.prepare(
  `INSERT INTO benchmark_result
       (model_id, benchmark_id, score, metric, self_reported, measured_at, source_snapshot_id)
     VALUES (?, ?, ?, 'score', ?, ?, ?)`
 )
 // The regression: same model + benchmark + provenance class. The dated 2024
 // row must NOT beat the newer NULL-measured row (snapshot 2026-09-03).
 insertResult.run(1, 'fixture_bench', 10, 0, '2024-05-01', 1)
 insertResult.run(1, 'fixture_bench', 55, 0, null, 2)
 // benchmark_timeseries (self_reported = 0): dated point + snapshot-dated point.
 insertResult.run(1, 'hle', 20, 0, '2025-01-15', 1)
 insertResult.run(1, 'hle', 31, 0, null, 2)
 // ELO series: measured point, snapshot-dated point, and an undatable row
 // (all three dates NULL) that must be dropped, never baked as NaN/"null".
 insertResult.run(1, 'lmarena_text_overall', 1300, 0, null, 2)
 insertResult.run(2, 'lmarena_text_overall', 1250, 0, '2026-02-02', 1)
 insertResult.run(3, 'lmarena_text_overall', 1200, 0, null, null)

 // Keep every output array non-empty (writeJson refuses empty arrays).
 insertResult.run(2, 'fixture_coding', 0.5, 0, '2026-02-04', 1)
 db.run(`UPDATE benchmark_result SET eval_condition_json = '{"mean_cost_usd":1.5,"mean_duration_seconds":120}'
          WHERE benchmark_id = 'fixture_coding'`)
 db.run(`INSERT INTO model_alias (model_id, source_id, alias_string, first_seen_at, source_snapshot_id)
          VALUES (1, 'fixture', 'new-model-alias', '2026-08-01', 2)`)
 db.run(`INSERT INTO price_component
            (id, model_id, component, unit, amount, normalized_usd_per_1m_tokens,
             source_id, source_snapshot_id, valid_from)
          VALUES (1, 1, 'input_token', 'USD', 1.0, 1.0, 'fixture', 2, '2026-08-01')`)
 insertResult.run(2, 'lmarena_text_coding', 1200, 0, '2026-02-03', 1)
 db.close()
}

function runExtract(dbPath, outDir) {
 const proc = Bun.spawnSync(['bun', EXTRACT], {
  env: { ...process.env, MODELDB_EXTRACT_DB: dbPath, MODELDB_EXTRACT_OUT: outDir },
  stdout: 'pipe',
  stderr: 'pipe',
 })
 if (proc.exitCode !== 0) {
  throw new Error(`extract.mjs failed (${proc.exitCode}): ${proc.stderr.toString()}`)
 }
}

describe('extract.mjs effective-date handling (NULL measured_at)', () => {
 const workDir = mkdtempSync(join(tmpdir(), 'modeldb-extract-test-'))
 const dbPath = join(workDir, 'fixture.sqlite')
 const outDir = join(workDir, 'out')
 buildFixture(dbPath)
 runExtract(dbPath, outDir)

 const readJson = (name) => JSON.parse(readFileSync(join(outDir, name), 'utf8'))

 test('headline ROW_NUMBER pick: NULL-measured newest row wins, measuredAt stays null', () => {
  // Negative control — the pre-fix ordering (bare measured_at DESC) lost the
  // NULL row to the dated 2024 row.
  const db = new Database(dbPath)
  const oldPick = db.query(`
      SELECT score FROM (
        SELECT model_id, benchmark_id, score,
          ROW_NUMBER() OVER (
            PARTITION BY model_id, benchmark_id
            ORDER BY self_reported ASC, measured_at DESC
          ) AS rn
        FROM benchmark_result WHERE score IS NOT NULL
      ) WHERE rn = 1 AND model_id = 1 AND benchmark_id = 'fixture_bench'`).get()
  db.close()
  expect(oldPick.score).toBe(10)

  const models = readJson('models.json')
  const picked = models.find((m) => m.id === 1).scores.fixture_bench
  expect(picked.score).toBe(55)
  expect(picked.measuredAt).toBeNull() // stored NULL stays NULL in the payload
 })

 test('benchmarks.json results: NULL-measured newest row sorts last (newest)', () => {
  const bench = readJson('benchmarks.json').find((b) => b.id === 'fixture_bench')
  expect(bench.results).toHaveLength(2)
  expect(bench.results[0].measuredAt).toBe('2024-05-01')
  expect(bench.results[0].score).toBe(10)
  expect(bench.results.at(-1).measuredAt).toBeNull()
  expect(bench.results.at(-1).score).toBe(55)
  expect(bench.results.at(-1).fetchedAt).toBe('2026-09-03T03:46:57+00:00')
 })

 test('benchmark_timeseries: buckets keep finite t and honest dateSource', () => {
  const series = readJson('benchmark_timeseries.json').hle.series
   .find((s) => s.modelId === 1)
  expect(series.t).toHaveLength(2)
  for (const t of series.t) expect(Number.isFinite(t)).toBe(true)
  expect(new Date(series.t[0]).toISOString().slice(0, 10)).toBe('2025-01-15')
  expect(new Date(series.t[1]).toISOString().slice(0, 10)).toBe('2026-09-03')
  expect(series.dateSource).toEqual(['measured', 'snapshot'])
 })

 test('elo series: snapshot fallback plots NULL-measured rows, undatable rows dropped', () => {
  const { models, series } = readJson('elo_text_overall.json')
  for (const s of series) for (const t of s.t) expect(Number.isFinite(t)).toBe(true)
  const byModel = new Map(series.map((s) => [s.modelId, s]))
  expect(byModel.get(1).dateSource).toEqual(['snapshot']) // NULL measured_at, snapshot-dated
  expect(byModel.get(2).dateSource).toEqual(['measured'])
  expect(models.some((m) => m.id === 3)).toBe(false) // no date anywhere: no point, no NaN
 })

 test('no "null" dateKeys or NaN timestamps in any generated JSON', () => {
  for (const name of [
   'elo_text_overall.json',
   'elo_text_coding.json',
   'benchmark_timeseries.json',
  ]) {
   const raw = readFileSync(join(outDir, name), 'utf8')
   expect(raw).not.toContain('NaN')
   expect(raw).not.toContain('null"') // a String(null).slice(0,10) dateKey
  }
 })
})
