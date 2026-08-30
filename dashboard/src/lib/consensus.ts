import type { Benchmark, BenchmarkResult, Model } from './data'

export interface ConsensusBenchmarkDef {
  id: string
  label: string
  kind?: 'benchmark' | 'modelScore'
  baseWeight?: number
}

export interface ConsensusOptions {
  benchmarkIds?: string[]
  benchmarks?: ConsensusBenchmarkDef[]
}

export interface ConsensusCellDetail {
  score: number
  percentile: number
  rank: number
  total: number
  date: string | null
  selfReported: boolean
  sourceId: string | null
  fetchedAt: string | null
  weight: number
}

export interface ConsensusRow {
  modelId: number
  modelName: string
  modelSlug: string
  developer: string | null
  openWeights: boolean
  scores: Record<string, ConsensusCellDetail>
  consensusScore: number
  disagreementScore: number
  benchmarkCount: number
}

export const DEFAULT_CONSENSUS_BENCHMARKS: ConsensusBenchmarkDef[] = [
  { id: 'lmarena_text_overall', label: 'Arena ELO', kind: 'modelScore', baseWeight: 1.25 },
  { id: 'gpqa_diamond', label: 'GPQA Diamond' },
  { id: 'hle', label: 'HLE (Reasoning)' },
  { id: 'scicode', label: 'SciCode' },
  { id: 'math_level_5', label: 'MATH L5' },
  { id: 'frontiermath', label: 'FrontierMath' },
  { id: 'swe_bench_verified', label: 'SWE Verified' },
  { id: 'deepswe', label: 'DeepSWE' },
  { id: 'aider_polyglot', label: 'Aider Polyglot' },
  { id: 'lcr', label: 'LCR (Coding)' },
  { id: 'tau2', label: 'TAU-Agent' },
  { id: 'terminalbench_hard', label: 'TerminalBench' },
  { id: 'ifbench', label: 'IFBench' },
]

const MIN_RELIABILITY_WEIGHT = 0.35
const RESIDUAL_SCALE = 20

function resolveBenchmarkDefs(options: ConsensusBenchmarkDef[] | ConsensusOptions): ConsensusBenchmarkDef[] {
  if (Array.isArray(options)) return options
  if (options.benchmarks) return options.benchmarks
  if (options.benchmarkIds) {
    return options.benchmarkIds.map((id) => {
      const existing = DEFAULT_CONSENSUS_BENCHMARKS.find((benchmark) => benchmark.id === id)
      if (existing) return existing
      return {
        id,
        label: id,
        kind: id.startsWith('lmarena_') ? 'modelScore' : 'benchmark',
        baseWeight: id.startsWith('lmarena_') ? 1.25 : 1,
      }
    })
  }
  return DEFAULT_CONSENSUS_BENCHMARKS
}

interface PercentileCell {
  score: number
  percentile: number
  rank: number
  total: number
  date: string | null
  selfReported: boolean
  sourceId: string | null
  fetchedAt: string | null
}

type PercentilesByBenchmark = Map<string, Map<number, PercentileCell>>

export function benchmarkReliabilityWeights(
  models: Model[],
  benchmarks: Benchmark[],
  options: ConsensusBenchmarkDef[] | ConsensusOptions = DEFAULT_CONSENSUS_BENCHMARKS,
): Map<string, number> {
  const benchmarkDefs = resolveBenchmarkDefs(options)
  const percentilesByBenchmark = buildPercentiles(models, benchmarks, benchmarkDefs)
  return reliabilityWeightsFromPercentiles(percentilesByBenchmark, benchmarkDefs)
}

function reliabilityWeightsFromPercentiles(
  percentilesByBenchmark: PercentilesByBenchmark,
  benchmarkDefs: ConsensusBenchmarkDef[],
): Map<string, number> {
  const weights = new Map<string, number>()
  const percentilesByModel = new Map<number, Map<string, number>>()

  for (const [benchmarkId, modelCells] of percentilesByBenchmark) {
    for (const [modelId, cell] of modelCells) {
      const modelPercentiles = percentilesByModel.get(modelId) ?? new Map<string, number>()
      modelPercentiles.set(benchmarkId, cell.percentile)
      percentilesByModel.set(modelId, modelPercentiles)
    }
  }

  const medianPercentileByModel = new Map<number, number>()
  for (const [modelId, modelPercentiles] of percentilesByModel) {
    medianPercentileByModel.set(modelId, median([...modelPercentiles.values()]))
  }

  for (const def of benchmarkDefs) {
    const modelCells = percentilesByBenchmark.get(def.id)
    if (!modelCells || modelCells.size === 0) {
      weights.set(def.id, def.baseWeight ?? 1)
      continue
    }

    let residualSum = 0
    let residualCount = 0
    for (const [modelId, cell] of modelCells) {
      const modelMedian = medianPercentileByModel.get(modelId)
      if (modelMedian == null) continue
      residualSum += Math.abs(cell.percentile - modelMedian)
      residualCount += 1
    }

    const meanAbsResidual = residualCount > 0 ? residualSum / residualCount : 0
    const reliability = 1 / (1 + Math.pow(meanAbsResidual / RESIDUAL_SCALE, 2))
    const baseWeight = def.baseWeight ?? 1
    weights.set(def.id, baseWeight * Math.max(MIN_RELIABILITY_WEIGHT, Math.min(1, reliability)))
  }

  return weights
}

export function buildConsensusRows(
  models: Model[],
  benchmarks: Benchmark[],
  options: ConsensusBenchmarkDef[] | ConsensusOptions = DEFAULT_CONSENSUS_BENCHMARKS,
): ConsensusRow[] {
  const benchmarkDefs = resolveBenchmarkDefs(options)
  const percentilesByBenchmark = buildPercentiles(models, benchmarks, benchmarkDefs)
  const weights = reliabilityWeightsFromPercentiles(percentilesByBenchmark, benchmarkDefs)

  return models
    .map((model) => {
      const rowScores: Record<string, ConsensusCellDetail> = {}
      const percentiles: number[] = []
      let weightedSum = 0
      let weightSum = 0

      for (const def of benchmarkDefs) {
        const cell = percentilesByBenchmark.get(def.id)?.get(model.id)
        if (!cell) continue

        const weight = weights.get(def.id) ?? def.baseWeight ?? 1
        rowScores[def.id] = { ...cell, weight }
        percentiles.push(cell.percentile)
        weightedSum += cell.percentile * weight
        weightSum += weight
      }

      return {
        modelId: model.id,
        modelName: model.name,
        modelSlug: model.slug,
        developer: model.dev,
        openWeights: model.open === 1,
        scores: rowScores,
        consensusScore: weightSum > 0 ? weightedSum / weightSum : 0,
        disagreementScore: standardDeviation(percentiles),
        benchmarkCount: percentiles.length,
      }
    })
    .sort((left, right) => right.consensusScore - left.consensusScore || left.modelName.localeCompare(right.modelName))
}

function buildPercentiles(
  models: Model[],
  benchmarks: Benchmark[],
  benchmarkDefs: ConsensusBenchmarkDef[],
): PercentilesByBenchmark {
  const benchmarkById = new Map(benchmarks.map((benchmark) => [benchmark.id, benchmark] as const))
  const percentilesByBenchmark: PercentilesByBenchmark = new Map()

  for (const def of benchmarkDefs) {
    if (def.kind === 'modelScore') {
      const cells = percentileCellsFromModelScores(models, def.id)
      if (cells.size > 0) percentilesByBenchmark.set(def.id, cells)
      continue
    }

    const benchmark = benchmarkById.get(def.id)
    if (!benchmark) continue

    const latestResults = latestBestResultsForBenchmark(benchmark)
    if (latestResults.size === 0) continue

    const cells = percentileCellsFromBenchmarkResults(latestResults, benchmark.higherIsBetter !== 0)
    if (cells.size > 0) percentilesByBenchmark.set(def.id, cells)
  }

  return percentilesByBenchmark
}

function latestBestResultsForBenchmark(benchmark: Benchmark): Map<number, BenchmarkResult> {
  const results = benchmark.results ?? []
  if (results.length === 0) return new Map()

  let latestSnapshotId = -1
  let latestFetchedTime = 0
  for (const result of results) {
    const fetchedTime = result.fetchedAt ? Date.parse(result.fetchedAt) : 0
    if (fetchedTime > latestFetchedTime) {
      latestFetchedTime = fetchedTime
      latestSnapshotId = result.sourceSnapshotId ?? -1
    } else if (
      fetchedTime === latestFetchedTime &&
      result.sourceSnapshotId != null &&
      result.sourceSnapshotId > latestSnapshotId
    ) {
      latestSnapshotId = result.sourceSnapshotId
    }
  }

  const latestResults = results.filter((result) => {
    const fetchedTime = result.fetchedAt ? Date.parse(result.fetchedAt) : 0
    const isLatestTime = fetchedTime === latestFetchedTime
    const isLatestSnapshot =
      result.sourceSnapshotId === undefined || latestSnapshotId === -1 || result.sourceSnapshotId === latestSnapshotId
    return isLatestTime && isLatestSnapshot
  })

  const latestMap = new Map<number, BenchmarkResult>()
  const higherIsBetter = benchmark.higherIsBetter !== 0
  for (const result of latestResults) {
    const existing = latestMap.get(result.modelId)
    if (!existing) {
      latestMap.set(result.modelId, result)
      continue
    }

    const isBetter = higherIsBetter ? result.score > existing.score : result.score < existing.score
    if (isBetter) latestMap.set(result.modelId, result)
  }

  return latestMap
}

function percentileCellsFromBenchmarkResults(
  resultsByModel: Map<number, BenchmarkResult>,
  higherIsBetter: boolean,
): Map<number, PercentileCell> {
  const sortedResults = [...resultsByModel.entries()].sort((left, right) =>
    higherIsBetter ? right[1].score - left[1].score : left[1].score - right[1].score,
  )
  const total = sortedResults.length
  const cells = new Map<number, PercentileCell>()

  sortedResults.forEach(([modelId, result], index) => {
    cells.set(modelId, {
      score: result.score,
      percentile: percentileFromRank(index + 1, total),
      rank: index + 1,
      total,
      date: result.measuredAt,
      selfReported: result.selfReported !== 0,
      sourceId: result.sourceId ?? null,
      fetchedAt: result.fetchedAt ?? null,
    })
  })

  return cells
}

function percentileCellsFromModelScores(models: Model[], benchmarkId: string): Map<number, PercentileCell> {
  const sortedScores = models
    .map((model) => {
      const score = model.scores[benchmarkId]
      return score ? { model, score } : null
    })
    .filter((entry): entry is { model: Model; score: Model['scores'][string] } => entry != null)
    .sort((left, right) => right.score.score - left.score.score)

  const total = sortedScores.length
  const cells = new Map<number, PercentileCell>()

  sortedScores.forEach(({ model, score }, index) => {
    cells.set(model.id, {
      score: score.score,
      percentile: percentileFromRank(index + 1, total),
      rank: index + 1,
      total,
      date: score.measuredAt,
      selfReported: score.selfReported !== 0,
      sourceId: benchmarkId,
      fetchedAt: null,
    })
  })

  return cells
}

function percentileFromRank(rank: number, total: number): number {
  return total > 1 ? (1 - (rank - 1) / (total - 1)) * 100 : 100
}

function median(values: number[]): number {
  if (values.length === 0) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle]
}

function standardDeviation(values: number[]): number {
  if (values.length <= 1) return 0
  const avg = values.reduce((sum, value) => sum + value, 0) / values.length
  const variance = values.reduce((sum, value) => sum + Math.pow(value - avg, 2), 0) / (values.length - 1)
  return Math.sqrt(variance)
}
