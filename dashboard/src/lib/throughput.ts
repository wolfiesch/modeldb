import type { Enrichment, Model } from './data'

export type ThroughputSource = 'local_omp' | 'artificialanalysis'

export interface ThroughputFile {
  generatedAt: string
  benchmarkId: 'omp_visible_output_tokens_per_second'
  rows: LocalThroughputRow[]
}

export interface LocalThroughputRow {
  modelId: number
  canonicalSlug: string
  modelName: string
  dev: string | null
  devName: string | null
  providerLabel: string
  ompSelector: string
  tps: number
  visibleCharsPerSecond: number | null
  durationMs: number | null
  measuredAt: string
  fetchedAt: string | null
  sourceSnapshotId: number | null
  artifactPath: string | null
  sourceHash: string | null
  runId: string | null
  tokenizer: string | null
}

export interface ThroughputRow {
  key: string
  modelId: number
  slug: string
  modelName: string
  dev: string | null
  devName: string | null
  providerLabel: string
  ompSelector: string | null
  tps: number
  source: ThroughputSource
  measuredAt: string | null
  fetchedAt: string | null
  sourceSnapshotId: number | null
  artifactPath: string | null
  sourceHash: string | null
  runId: string | null
  tokenizer: string | null
}

export interface CoinPlan {
  count: number
  fallSpeed: number
  coinsPerSecond: number
}

export function buildThroughputRows(
  models: Model[],
  enrichment: Enrichment,
  local: ThroughputFile | null,
  options?: { maxRows?: number; source?: 'all' | 'local_omp' | 'artificialanalysis' },
): ThroughputRow[] {
  const maxRows = options?.maxRows ?? 40
  const source = options?.source ?? 'all'
  const rows: ThroughputRow[] = []
  const modelById = new Map(models.map((model) => [model.id, model]))
  if (source === 'all' || source === 'local_omp') {
    for (const row of local?.rows ?? []) {
      if (!isValidTps(row.tps)) continue
      const model = modelById.get(row.modelId)
      const normalized: ThroughputRow = {
        key: `local_omp:${row.ompSelector}`,
        modelId: row.modelId,
        slug: model?.slug ?? row.canonicalSlug,
        modelName: model?.name ?? row.modelName,
        dev: model?.dev ?? row.dev,
        devName: model?.devName ?? row.devName,
        providerLabel: row.providerLabel,
        ompSelector: row.ompSelector,
        tps: row.tps,
        source: 'local_omp',
        measuredAt: row.measuredAt,
        fetchedAt: row.fetchedAt,
        sourceSnapshotId: row.sourceSnapshotId,
        artifactPath: row.artifactPath,
        sourceHash: row.sourceHash,
        runId: row.runId,
        tokenizer: row.tokenizer,
      }
      rows.push(normalized)
    }
  }

  if (source === 'all' || source === 'artificialanalysis') {
    for (const model of models) {
      const signal = enrichment[String(model.id)]?.medianOutputTokensPerSecond
      const tps = Number(signal?.value)
      if (!isValidTps(tps)) continue
      rows.push({
        key: `artificialanalysis:${model.slug}`,
        modelId: model.id,
        slug: model.slug,
        modelName: model.name,
        dev: model.dev,
        devName: model.devName,
        providerLabel: 'Artificial Analysis median',
        ompSelector: null,
        tps,
        source: 'artificialanalysis',
        measuredAt: null,
        fetchedAt: signal?.fetchedAt ?? null,
        sourceSnapshotId: signal?.sourceSnapshotId ?? null,
        artifactPath: null,
        sourceHash: null,
        runId: null,
        tokenizer: null,
      })
    }
  }

  return rows.sort((a, b) => b.tps - a.tps).slice(0, maxRows)
}

export function coinPlanForThroughput(tps: number): CoinPlan {
  const safeTps = Math.max(0, Number.isFinite(tps) ? tps : 0)
  const fallSpeed = 1.15
  const count = Math.max(6, Math.min(600, Math.round(safeTps * 0.6)))
  return {
    count,
    fallSpeed,
    coinsPerSecond: safeTps * 0.6 * (fallSpeed / 9.5),
  }
}

function isValidTps(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}
