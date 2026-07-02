// Bake db/modeldb.sqlite into static JSON for the dashboard SPA.
// DB open mirrors viz/lib/render.mjs: NO readonly flag — readonly fails to
// attach the WAL sidecar on this DB.

import { Database } from 'bun:sqlite'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mkdirSync, existsSync, writeFileSync } from 'node:fs'

const scriptsDir = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = resolve(scriptsDir, '../..')
const DB_PATH = resolve(REPO_ROOT, 'db/modeldb.sqlite')
const OUT_DIR = resolve(REPO_ROOT, 'dashboard/public/data')

if (!existsSync(DB_PATH)) {
  throw new Error(`DB not found: ${DB_PATH}`)
}
mkdirSync(OUT_DIR, { recursive: true })

const db = new Database(DB_PATH) // NOT {readonly:true} — see header
const q = (sql, params = []) => db.query(sql).all(...params)

// --- ported from viz/lib/theme.mjs -----------------------------------------
function shortName(slug) {
  let name = String(slug).split('/').pop() ?? String(slug)
  name = name.replace(/-\d{4}-?\d{2}-?\d{2}$/, '')
  name = name.replace(/(\d)-(\d)/g, '$1.$2')
  name = name.replace(
    /^claude-(\d+(?:\.\d+)?)-(haiku|sonnet|opus)/i,
    (_, gen, tier) => `${tier}-${gen}`
  )
  name = name
    .replace(/^claude-/, '')
    .replace(/^gemini-/, '')
    .replace(/^gpt-/, 'GPT-')
    .replace(/-/g, ' ')
    .replace(/\b([a-z])/g, (letter) => letter.toUpperCase())
    .trim()
  const BRAND_CASING = [
    [/\bGlm\b/g, 'GLM'],
    [/\bDeepseek\b/g, 'DeepSeek'],
    [/\bKimi K2\b/g, 'Kimi K2'],
    [/\bMimo\b/g, 'MiMo'],
    [/\bQwq\b/g, 'QwQ'],
    [/\bLlama\b/g, 'Llama']
  ]
  for (const [pattern, replacement] of BRAND_CASING) {
    name = name.replace(pattern, replacement)
  }
  return name
}

// --- ported from viz/lib/peers.mjs ------------------------------------------
// Standard/base-tier price ($ per 1M tokens): MODE of non-zero normalized
// values; ties break to the lower (base) price. Returns null if none.
function standardPrice(modelId, component, sourceId = 'models_dev') {
  const rows = q(
    `SELECT normalized_usd_per_1m_tokens AS v FROM price_component
     WHERE model_id = ? AND source_id = ? AND component = ?
       AND normalized_usd_per_1m_tokens IS NOT NULL
       AND normalized_usd_per_1m_tokens > 0`,
    [modelId, sourceId, component]
  )
  if (rows.length === 0) return null
  const counts = new Map()
  for (const { v } of rows) counts.set(v, (counts.get(v) ?? 0) + 1)
  let best = null
  let bestCount = -1
  for (const [value, count] of counts) {
    if (count > bestCount || (count === bestCount && value < best)) {
      best = value
      bestCount = count
    }
  }
  return best
}

function writeJson(name, value) {
  if (Array.isArray(value) && value.length === 0) {
    throw new Error(`extract: refusing to write empty array to ${name}`)
  }
  const path = resolve(OUT_DIR, name)
  const text = JSON.stringify(value)
  writeFileSync(path, text)
  console.log(`${name} ${(text.length / 1024).toFixed(0)} KB`)
}

// --- 1. meta.json ------------------------------------------------------------
const counts = {
  models: q('SELECT COUNT(*) AS n FROM model')[0].n,
  aliases: q('SELECT COUNT(*) AS n FROM model_alias')[0].n,
  benchmarkResults: q('SELECT COUNT(*) AS n FROM benchmark_result')[0].n,
  priceComponents: q('SELECT COUNT(*) AS n FROM price_component')[0].n
}
if (counts.models === 0) throw new Error('extract: model table is empty')
const snapshots = q(
  `SELECT ss.source_id AS sourceId, s.name AS sourceName, ss.url, ss.fetched_at AS fetchedAt
   FROM source_snapshot ss JOIN source s ON s.id = ss.source_id
   ORDER BY ss.fetched_at`
)
writeJson('meta.json', { generatedAt: new Date().toISOString(), counts, snapshots })

// --- 2. models.json ----------------------------------------------------------
const capMax = new Map() // `${modelId}:${cap}` -> max numeric value
for (const r of q(
  `SELECT model_id, capability, MAX(CAST(value AS INTEGER)) AS v
   FROM model_capability
   WHERE capability IN ('context_window','max_output') AND value GLOB '[0-9]*'
   GROUP BY model_id, capability`
)) {
  capMax.set(`${r.model_id}:${r.capability}`, r.v)
}
const capAny = new Map() // `${modelId}:${cap}` -> one value
for (const r of q(
  `SELECT model_id, capability, value FROM model_capability
   WHERE capability IN ('input_modalities','output_modalities')`
)) {
  capAny.set(`${r.model_id}:${r.capability}`, r.value)
}

// Latest score per (model, benchmark).
const latestScores = new Map() // modelId -> { benchId: {...} }
for (const r of q(
  `SELECT model_id, benchmark_id, score, rank, self_reported, measured_at
   FROM (
     SELECT model_id, benchmark_id, score, rank, self_reported, measured_at,
       ROW_NUMBER() OVER (PARTITION BY model_id, benchmark_id ORDER BY measured_at DESC) AS rn
     FROM benchmark_result WHERE score IS NOT NULL
   ) WHERE rn = 1`
)) {
  let m = latestScores.get(r.model_id)
  if (!m) latestScores.set(r.model_id, (m = {}))
  m[r.benchmark_id] = {
    score: r.score,
    rank: r.rank,
    selfReported: r.self_reported,
    measuredAt: r.measured_at
  }
}

function parseModalities(text) {
  if (text == null) return null
  try {
    const parsed = JSON.parse(text)
    return Array.isArray(parsed) ? parsed : [String(parsed)]
  } catch {
    return [String(text)]
  }
}

const models = q(
  `SELECT m.id, m.canonical_slug, m.developer_id, o.display_name AS dev_name,
          m.family, m.generation, m.tier_or_variant, m.parameter_scale,
          m.training_role, m.release_date, m.knowledge_cutoff, m.stability,
          m.open_weights
   FROM model m LEFT JOIN organization o ON o.id = m.developer_id
   ORDER BY m.canonical_slug`
).map((m) => ({
  id: m.id,
  slug: m.canonical_slug,
  name: shortName(m.canonical_slug),
  dev: m.developer_id,
  devName: m.dev_name,
  family: m.family,
  generation: m.generation,
  tier: m.tier_or_variant,
  params: m.parameter_scale,
  role: m.training_role,
  released: m.release_date,
  cutoff: m.knowledge_cutoff,
  stability: m.stability,
  open: m.open_weights,
  ctx: capMax.get(`${m.id}:context_window`) ?? null,
  maxOut: capMax.get(`${m.id}:max_output`) ?? null,
  inMod: parseModalities(capAny.get(`${m.id}:input_modalities`)),
  outMod: parseModalities(capAny.get(`${m.id}:output_modalities`)),
  priceIn: standardPrice(m.id, 'input_token'),
  priceOut: standardPrice(m.id, 'output_token'),
  priceCacheRead: standardPrice(m.id, 'cache_read'),
  priceCacheWrite: standardPrice(m.id, 'cache_write'),
  scores: latestScores.get(m.id) ?? {}
}))
writeJson('models.json', models)

// --- 3. benchmarks.json -------------------------------------------------------
const benchmarks = q(
  `SELECT id, name, category, metric_default AS metricDefault,
          higher_is_better AS higherIsBetter, source_url AS sourceUrl
   FROM benchmark ORDER BY id`
).map((b) => {
  const results = b.id.startsWith('lmarena_')
    ? undefined
    : q(
        `SELECT model_id AS modelId, score, metric, rank,
                self_reported AS selfReported, measured_at AS measuredAt
         FROM benchmark_result
         WHERE benchmark_id = ? AND score IS NOT NULL
         ORDER BY measured_at`,
        [b.id]
      )
  return results ? { ...b, results } : b
})
writeJson('benchmarks.json', benchmarks)

// --- 4. elo_*.json (columnar) --------------------------------------------------
function emitElo(benchmarkId, filename) {
  const rows = q(
    `SELECT model_id, score, rank, measured_at
     FROM benchmark_result
     WHERE benchmark_id = ? AND score IS NOT NULL
     ORDER BY model_id, measured_at`,
    [benchmarkId]
  )
  const perModel = new Map() // modelId -> Map(dateKey -> {t, elo, rank})
  for (const r of rows) {
    let m = perModel.get(r.model_id)
    if (!m) perModel.set(r.model_id, (m = new Map()))
    const dateKey = String(r.measured_at).slice(0, 10)
    m.set(dateKey, { t: Date.parse(r.measured_at), elo: r.score, rank: r.rank })
  }
  const modelMeta = new Map(models.map((m) => [m.id, m]))
  const series = []
  const usedModels = []
  for (const [modelId, points] of perModel) {
    const meta = modelMeta.get(modelId)
    if (!meta) continue
    const sorted = [...points.values()].sort((a, b) => a.t - b.t)
    series.push({
      modelId,
      t: sorted.map((p) => p.t),
      elo: sorted.map((p) => p.elo),
      rank: sorted.map((p) => p.rank)
    })
    usedModels.push({ id: meta.id, slug: meta.slug, dev: meta.dev })
  }
  if (series.length === 0) throw new Error(`extract: no ELO series for ${benchmarkId}`)
  writeJson(filename, { models: usedModels, series })
}
emitElo('lmarena_text_overall', 'elo_text_overall.json')
emitElo('lmarena_text_coding', 'elo_text_coding.json')

// --- 5. prices.json -------------------------------------------------------------
const priceRows = q(
  `SELECT model_id, component, unit, amount,
          normalized_usd_per_1m_tokens AS usdPer1m, source_id AS sourceId,
          valid_from AS validFrom, valid_to AS validTo,
          tier_condition_json AS tierCondition
   FROM price_component
   WHERE model_id IS NOT NULL
   ORDER BY model_id, component, valid_from`
)
const priceByModel = new Map()
for (const r of priceRows) {
  let entry = priceByModel.get(r.model_id)
  if (!entry) priceByModel.set(r.model_id, (entry = { modelId: r.model_id, rows: [] }))
  entry.rows.push({
    component: r.component,
    unit: r.unit,
    amount: r.amount,
    usdPer1m: r.usdPer1m,
    sourceId: r.sourceId,
    validFrom: r.validFrom,
    validTo: r.validTo,
    tierCondition: r.tierCondition ? JSON.parse(r.tierCondition) : null
  })
}
writeJson('prices.json', [...priceByModel.values()])

// --- 6. aliases.json --------------------------------------------------------------
const aliases = q(
  `SELECT model_id AS modelId, source_id AS sourceId, alias_string AS alias,
          alias_kind AS kind, resolution_method AS method, confidence,
          first_seen_at AS firstSeen, last_seen_at AS lastSeen
   FROM model_alias ORDER BY model_id, source_id, alias_string`
)
writeJson('aliases.json', aliases)

db.close()
console.log('extract: done')
