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

function parseJsonObject(text) {
  if (!text) return {}
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function firstValue(object, keys) {
  for (const key of keys) {
    if (object[key] !== undefined && object[key] !== null && object[key] !== '') {
      return object[key]
    }
  }
  return null
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function booleanOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value === 1 ? true : value === 0 ? false : null
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    if (['true', 'yes', '1', 'supported'].includes(normalized)) return true
    if (['false', 'no', '0', 'unsupported'].includes(normalized)) return false
  }
  return null
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
const capAny = new Map() // `${modelId}:${cap}` -> selected modality value
for (const r of q(
  `WITH latest_snapshot AS (
     SELECT source_id, MAX(id) AS snapshot_id
     FROM source_snapshot
     GROUP BY source_id
   ),
   ranked AS (
     SELECT mc.model_id, mc.capability, mc.value,
            ROW_NUMBER() OVER (
              PARTITION BY mc.model_id, mc.capability
              ORDER BY
                CASE ss.source_id
                  WHEN 'models_dev' THEN 3
                  WHEN 'openrouter' THEN 2
                  WHEN 'huggingface' THEN 1
                  ELSE 0
                END DESC,
                COALESCE(mc.confidence, 0) DESC,
                ss.fetched_at DESC,
                ss.id DESC
            ) AS rn
     FROM model_capability mc
     JOIN source_snapshot ss ON ss.id = mc.source_snapshot_id
     JOIN latest_snapshot ls ON ls.source_id = ss.source_id AND ls.snapshot_id = ss.id
     WHERE mc.capability IN ('input_modalities','output_modalities')
   )
   SELECT model_id, capability, value FROM ranked WHERE rn = 1`
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

const ARTIFICIAL_ANALYSIS_BENCHMARK_IDS = new Set([
  'artificial_analysis_intelligence_index',
  'artificial_analysis_coding_index',
  'artificial_analysis_math_index',
  'mmlu_pro',
  'gpqa',
  'hle',
  'livecodebench',
  'aime',
  'aime_25',
  'math_500',
  'ifbench',
  'lcr',
  'scicode',
  'tau2',
  'tau_banking',
  'terminalbench_hard',
  'terminalbench_v2_1'
])

// --- 3. enrichment.json -------------------------------------------------------
const enrichmentByModel = new Map(
  models.map((model) => [
    model.id,
    {
      modelId: model.id,
      artificialAnalysis: {},
      medianOutputTokensPerSecond: null,
      medianTimeToFirstTokenSeconds: null,
      medianTimeToFirstAnswerToken: null,
      artificialAnalysisReleaseDate: null,
      vllm: { supported: null, architecture: null, backend: null }
    }
  ])
)

for (const r of q(
  `SELECT model_id AS modelId, benchmark_id AS benchmarkId, score, metric, rank,
          self_reported AS selfReported, measured_at AS measuredAt,
          source_snapshot_id AS sourceSnapshotId, source_id AS sourceId, fetched_at AS fetchedAt
   FROM (
     SELECT br.model_id, br.benchmark_id, br.score, br.metric, br.rank,
            br.self_reported, br.measured_at, br.source_snapshot_id,
            ss.source_id, ss.fetched_at,
            ROW_NUMBER() OVER (
              PARTITION BY br.model_id, br.benchmark_id
              ORDER BY br.measured_at DESC, br.id DESC
            ) AS rn
     FROM benchmark_result br
     LEFT JOIN source_snapshot ss ON ss.id = br.source_snapshot_id
     WHERE ss.source_id = 'artificialanalysis' AND br.score IS NOT NULL
   ) WHERE rn = 1`
)) {
  if (!ARTIFICIAL_ANALYSIS_BENCHMARK_IDS.has(r.benchmarkId)) continue
  const entry = enrichmentByModel.get(r.modelId)
  if (!entry) continue
  entry.artificialAnalysis[r.benchmarkId] = {
    score: r.score,
    metric: r.metric,
    rank: r.rank,
    selfReported: r.selfReported,
    measuredAt: r.measuredAt,
    sourceSnapshotId: r.sourceSnapshotId,
    sourceId: r.sourceId,
    fetchedAt: r.fetchedAt
  }
}

const enrichmentCapabilityMap = {
  median_output_tokens_per_second: ['medianOutputTokensPerSecond', 'number'],
  median_time_to_first_token_seconds: ['medianTimeToFirstTokenSeconds', 'number'],
  median_time_to_first_answer_token: ['medianTimeToFirstAnswerToken', 'number'],
  artificial_analysis_release_date: ['artificialAnalysisReleaseDate', 'string'],
  vllm_supported: ['vllm.supported', 'boolean'],
  vllm_architecture: ['vllm.architecture', 'string'],
  vllm_backend: ['vllm.backend', 'string']
}

for (const r of q(
  `SELECT model_id AS modelId, capability, value, confidence,
          source_snapshot_id AS sourceSnapshotId, source_id AS sourceId, fetched_at AS fetchedAt
   FROM (
     SELECT mc.model_id, mc.capability, mc.value, mc.confidence, mc.source_snapshot_id,
            ss.source_id, ss.fetched_at,
            ROW_NUMBER() OVER (
              PARTITION BY mc.model_id, mc.capability
              ORDER BY ss.fetched_at DESC, mc.source_snapshot_id DESC
            ) AS rn
     FROM model_capability mc
     LEFT JOIN source_snapshot ss ON ss.id = mc.source_snapshot_id
     WHERE mc.capability IN (
       'median_output_tokens_per_second',
       'median_time_to_first_token_seconds',
       'median_time_to_first_answer_token',
       'artificial_analysis_release_date',
       'vllm_supported',
       'vllm_architecture',
       'vllm_backend'
     )
   ) WHERE rn = 1`
)) {
  const entry = enrichmentByModel.get(r.modelId)
  const config = enrichmentCapabilityMap[r.capability]
  if (!entry || !config) continue

  const [path, valueType] = config
  const value =
    valueType === 'number'
      ? numberOrNull(r.value)
      : valueType === 'boolean'
        ? booleanOrNull(r.value)
        : r.value
  if (value == null) continue

  const signal = {
    value,
    sourceSnapshotId: r.sourceSnapshotId,
    sourceId: r.sourceId,
    fetchedAt: r.fetchedAt,
    confidence: r.confidence
  }
  if (path.startsWith('vllm.')) {
    entry.vllm[path.slice('vllm.'.length)] = signal
  } else {
    entry[path] = signal
  }
}

writeJson('enrichment.json', Object.fromEntries(enrichmentByModel))

// --- 4. benchmarks.json -------------------------------------------------------
const benchmarks = q(
  `SELECT id, name, category, metric_default AS metricDefault,
          higher_is_better AS higherIsBetter, source_url AS sourceUrl
   FROM benchmark ORDER BY id`
).map((b) => {
  const unresolvedCount = b.id.startsWith('lmarena_')
    ? 0
    : q(
        `SELECT COUNT(*) AS n
         FROM benchmark_result
         WHERE benchmark_id = ? AND score IS NOT NULL AND model_id IS NULL`,
        [b.id]
      )[0].n
  const results = b.id.startsWith('lmarena_')
    ? undefined
    : q(
        `SELECT br.model_id AS modelId, br.score, br.metric, br.rank,
                br.self_reported AS selfReported, br.measured_at AS measuredAt,
                ss.source_id AS sourceId, br.source_snapshot_id AS sourceSnapshotId,
                ss.fetched_at AS fetchedAt, br.ci, br.votes,
                br.eval_condition_json AS evalCondition
         FROM benchmark_result br
         LEFT JOIN source_snapshot ss ON ss.id = br.source_snapshot_id
         WHERE br.benchmark_id = ? AND br.score IS NOT NULL AND br.model_id IS NOT NULL
         ORDER BY br.measured_at`,
        [b.id]
      ).map((r) => ({
        ...r,
        evalCondition: r.evalCondition ? JSON.parse(r.evalCondition) : null
      }))
  return results ? { ...b, results, unresolvedCount } : { ...b, unresolvedCount }
})
writeJson('benchmarks.json', benchmarks)

// --- 4b. coding_agent_efficiency.json -----------------------------------------
const codingAgentResults = q(`
  SELECT br.id, br.benchmark_id AS benchmarkId, br.model_id AS modelId, br.score,
         br.eval_condition_json AS condJson, br.raw_record_json AS rawJson
  FROM benchmark_result br
  JOIN benchmark b ON b.id = br.benchmark_id
  WHERE b.category IN ('coding', 'agentic') AND br.score IS NOT NULL
`).map((r) => {
  const cond = r.condJson ? JSON.parse(r.condJson) : {}
  const raw = r.rawJson ? JSON.parse(r.rawJson) : {}

  const cost = cond.mean_cost_usd ?? cond.median_cost_usd ?? raw.total_cost ?? raw.cost ?? raw.instance_cost ?? null
  const duration = cond.mean_duration_seconds ?? cond.median_duration_seconds ?? raw.seconds_per_case ?? null
  const steps = cond.mean_agent_steps ?? cond.median_agent_steps ?? raw.instance_calls ?? null
  const inTokens = cond.mean_input_tokens ?? cond.median_input_tokens ?? null
  const outTokens = cond.mean_output_tokens ?? cond.median_output_tokens ?? null
  const peakContext = cond.median_peak_context_tokens ?? null

  const syntaxErrors = raw.syntax_errors ?? null
  const indentationErrors = raw.indentation_errors ?? null
  const malformedResponses = raw.num_malformed_responses ?? null
  const contextExhaustions = raw.exhausted_context_windows ?? null
  const timeouts = raw.test_timeouts ?? null

  const editFormat = cond.edit_format ?? raw.edit_format ?? null
  const harness = cond.harness ?? raw.harness ?? null
  const reasoningEffort = cond.reasoning_effort ?? raw.reasoning_effort ?? null

  return {
    resultId: r.id,
    benchmarkId: r.benchmarkId,
    modelId: r.modelId,
    score: r.score,
    cost,
    duration,
    steps,
    inTokens,
    outTokens,
    peakContext,
    syntaxErrors,
    indentationErrors,
    malformedResponses,
    contextExhaustions,
    timeouts,
    editFormat,
    harness,
    reasoningEffort
  }
}).filter((x) => x.cost !== null || x.duration !== null || x.steps !== null || x.syntaxErrors !== null)

writeJson('coding_agent_efficiency.json', codingAgentResults)

// --- 5. elo_*.json (columnar) --------------------------------------------------
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

// --- 5b. benchmark_timeseries.json --------------------------------------------
const timeseriesBenchmarks = [
  'gpqa_diamond', 'hle', 'scicode', 'math_level_5', 'frontiermath',
  'swe_bench_verified', 'deepswe', 'aider_polyglot', 'lcr', 'tau2',
  'terminalbench_hard', 'ifbench', 'epoch_capabilities_index'
]
const timeseriesData = {}

for (const benchId of timeseriesBenchmarks) {
  const rows = q(
    `SELECT br.model_id AS modelId, br.score, br.rank, br.measured_at AS measuredAt,
            ss.fetched_at AS fetchedAt, br.source_snapshot_id AS sourceSnapshotId
     FROM benchmark_result br
     LEFT JOIN source_snapshot ss ON ss.id = br.source_snapshot_id
     WHERE br.benchmark_id = ? AND br.score IS NOT NULL
     ORDER BY br.model_id, br.measured_at`,
    [benchId]
  )

  if (rows.length === 0) continue

  const perModel = new Map()
  for (const r of rows) {
    const dateStr = r.measuredAt || r.fetchedAt
    if (!dateStr) continue
    let m = perModel.get(r.modelId)
    if (!m) perModel.set(r.modelId, (m = new Map()))
    const dateKey = dateStr.slice(0, 10)
    const existing = m.get(dateKey)
    const currentSnap = r.sourceSnapshotId ?? -1
    if (!existing || currentSnap > existing.sourceSnapshotId) {
      m.set(dateKey, {
        t: Date.parse(dateStr),
        score: r.score,
        rank: r.rank,
        sourceSnapshotId: currentSnap
      })
    }
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
      score: sorted.map((p) => p.score),
      rank: sorted.map((p) => p.rank)
    })
    usedModels.push({ id: meta.id, slug: meta.slug, dev: meta.dev })
  }

  if (series.length > 0) {
    timeseriesData[benchId] = { models: usedModels, series }
  }
}
writeJson('benchmark_timeseries.json', timeseriesData)

// --- 6. prices.json -------------------------------------------------------------
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

// --- 7. aliases.json --------------------------------------------------------------
const aliases = q(
  `SELECT model_id AS modelId, source_id AS sourceId, alias_string AS alias,
          alias_kind AS kind, resolution_method AS method, confidence,
          first_seen_at AS firstSeen, last_seen_at AS lastSeen
   FROM model_alias ORDER BY model_id, source_id, alias_string`
)
writeJson('aliases.json', aliases)

// --- 8. run_options.json ---------------------------------------------------------
const runOptionsByModel = new Map(models.map((m) => [m.id, { modelId: m.id, surfaces: [], artifacts: [] }]))

const surfaceRows = q(
  `SELECT ps.id, ps.model_id AS modelId, ps.provider_id AS providerId,
          ps.surface_type AS surfaceType, ps.region,
          ps.endpoint_model_id AS endpointModelId,
          ps.metadata_json AS metadataJson, ss.source_id AS sourceId,
          m.open_weights AS modelOpenWeights
   FROM provider_surface ps
   JOIN model m ON m.id = ps.model_id
   LEFT JOIN source_snapshot ss ON ss.id = ps.source_snapshot_id
   WHERE ps.model_id IS NOT NULL
   ORDER BY ps.model_id, ps.provider_id, ps.surface_type, ps.region, ps.endpoint_model_id`
)

const surfaceById = new Map()
for (const r of surfaceRows) {
  const entry = runOptionsByModel.get(r.modelId)
  if (!entry) continue

  const metadata = parseJsonObject(r.metadataJson)
  const surface = {
    providerId: r.providerId,
    surfaceType: r.surfaceType,
    region: r.region,
    endpointModelId: r.endpointModelId,
    contextWindow: numberOrNull(
      firstValue(metadata, [
        'contextWindow',
        'context_window',
        'contextLength',
        'context_length',
        'max_input_tokens',
        'input_limit'
      ])
    ),
    maxOutput: numberOrNull(
      firstValue(metadata, [
        'maxOutput',
        'max_output',
        'max_completion_tokens',
        'top_provider_max_completion_tokens',
        'max_output_tokens',
        'output_limit'
      ])
    ),
    toolCall: booleanOrNull(firstValue(metadata, ['toolCall', 'tool_call', 'tools', 'supports_tools'])),
    reasoning: booleanOrNull(firstValue(metadata, ['reasoning', 'supports_reasoning'])),
    openWeights: booleanOrNull(firstValue(metadata, ['openWeights', 'open_weights'])) ?? booleanOrNull(r.modelOpenWeights),
    sourceId: r.sourceId,
    prices: []
  }
  entry.surfaces.push(surface)
  surfaceById.set(r.id, surface)
}

for (const r of q(
  `SELECT provider_surface_id AS surfaceId, component, unit, amount,
          normalized_usd_per_1m_tokens AS usdPer1m, source_id AS sourceId
   FROM price_component
   WHERE provider_surface_id IS NOT NULL
   ORDER BY provider_surface_id, component, valid_from`
)) {
  const surface = surfaceById.get(r.surfaceId)
  if (!surface) continue
  surface.prices.push({
    component: r.component,
    unit: r.unit,
    amount: r.amount,
    usdPer1m: r.usdPer1m,
    sourceId: r.sourceId
  })
}

const artifactById = new Map()
for (const r of q(
  `SELECT id, model_id AS modelId, source_id AS sourceId,
          artifact_ref AS artifactRef, artifact_type AS artifactType,
          author, gated, license, sha, last_modified AS lastModified
   FROM model_artifact
   WHERE model_id IS NOT NULL
   ORDER BY model_id, artifact_ref`
)) {
  const entry = runOptionsByModel.get(r.modelId)
  if (!entry) continue
  const artifact = {
    sourceId: r.sourceId,
    artifactRef: r.artifactRef,
    artifactType: r.artifactType,
    author: r.author,
    gated: r.gated,
    license: r.license,
    sha: r.sha,
    lastModified: r.lastModified,
    variants: []
  }
  entry.artifacts.push(artifact)
  artifactById.set(r.id, artifact)
}

for (const r of q(
  `SELECT artifact_id AS artifactId, quantization, format,
          parameter_count AS parameterCount, file_pattern AS filePattern,
          metadata_json AS metadataJson
   FROM artifact_variant
   ORDER BY artifact_id, quantization, format, file_pattern`
)) {
  const artifact = artifactById.get(r.artifactId)
  if (!artifact) continue
  const metadata = parseJsonObject(r.metadataJson)
  artifact.variants.push({
    quantization: r.quantization,
    format: r.format,
    parameterCount: r.parameterCount,
    filePattern: r.filePattern,
    sizeBytes: numberOrNull(firstValue(metadata, ['sizeBytes', 'size_bytes', 'size']))
  })
}

writeJson('run_options.json', [...runOptionsByModel.values()])

db.close()
console.log('extract: done')
