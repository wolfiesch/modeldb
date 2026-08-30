import { describe, expect, test } from 'bun:test'
import type { Benchmark, BenchmarkResult, Model, Score } from './data'
import { benchmarkReliabilityWeights, buildConsensusRows } from './consensus'

const STABLE_A = 'stable_reasoning_a'
const STABLE_B = 'stable_reasoning_b'
const NOISY_FLIP = 'noisy_rank_flip'
const ARENA = 'lmarena_text_overall'

type WeightLookup = Record<string, number> | Map<string, number>

type ConsensusRowForTest = {
  modelId: number
  modelName: string
  modelSlug: string
  openWeights: boolean
  scores: Record<string, { score: number; percentile: number }>
  consensusScore: number
  disagreementScore: number
  benchmarkCount: number
}

function model(id: number, slug: string, scores: Record<string, Score> = {}, open = false): Model {
  return {
    id,
    slug,
    name: slug,
    dev: 'test-lab',
    devName: 'Test Lab',
    family: null,
    generation: null,
    tier: null,
    params: null,
    role: null,
    released: null,
    cutoff: null,
    stability: null,
    open: open ? 1 : 0,
    ctx: null,
    maxOut: null,
    inMod: null,
    outMod: null,
    priceIn: null,
    priceOut: null,
    priceCacheRead: null,
    priceCacheWrite: null,
    scores,
  }
}

function score(value: number): Score {
  return {
    score: value,
    metric: 'score',
    rank: null,
    selfReported: 0,
    measuredAt: null,
  }
}

function result(modelId: number, value: number): BenchmarkResult {
  return {
    modelId,
    score: value,
    metric: 'score',
    rank: null,
    selfReported: 0,
    measuredAt: null,
    sourceId: 'fixture',
    sourceSnapshotId: 1,
    fetchedAt: '2026-07-02T00:00:00.000Z',
  }
}

function benchmark(id: string, rows: Array<[modelId: number, value: number]>): Benchmark {
  return {
    id,
    name: id,
    category: 'fixture',
    metricDefault: 'score',
    higherIsBetter: 1,
    sourceUrl: null,
    results: rows.map(([modelId, value]) => result(modelId, value)),
  }
}

function weightFor(weights: WeightLookup, id: string): number {
  const value = weights instanceof Map ? weights.get(id) : weights[id]
  expect(value).toBeNumber()
  return value
}

function rowFor(rows: ConsensusRowForTest[], slug: string): ConsensusRowForTest {
  const row = rows.find((candidate) => candidate.modelSlug === slug)
  expect(row).toBeDefined()
  return row as ConsensusRowForTest
}

function buildRows(
  models: Model[],
  benchmarks: Benchmark[],
  benchmarkIds: string[],
): ConsensusRowForTest[] {
  return buildConsensusRows(models, benchmarks, { benchmarkIds }) as ConsensusRowForTest[]
}

describe('consensus reliability weighting', () => {
  test('benchmarkReliabilityWeights downweights a rank-flipping benchmark without dropping it below the floor', () => {
    const models = [
      model(1, 'consistent-top'),
      model(2, 'consistent-second'),
      model(3, 'consistent-third'),
      model(4, 'noisy-favorite'),
    ]
    const benchmarks = [
      benchmark(STABLE_A, [
        [1, 100],
        [2, 90],
        [3, 80],
        [4, 70],
      ]),
      benchmark(STABLE_B, [
        [1, 98],
        [2, 88],
        [3, 78],
        [4, 68],
      ]),
      benchmark(NOISY_FLIP, [
        [4, 100],
        [3, 90],
        [2, 80],
        [1, 70],
      ]),
    ]

    const weights = benchmarkReliabilityWeights(models, benchmarks, {
      benchmarkIds: [STABLE_A, STABLE_B, NOISY_FLIP],
    }) as WeightLookup

    const stableAWeight = weightFor(weights, STABLE_A)
    const stableBWeight = weightFor(weights, STABLE_B)
    const noisyWeight = weightFor(weights, NOISY_FLIP)

    expect(noisyWeight).toBeLessThan(stableAWeight)
    expect(noisyWeight).toBeLessThan(stableBWeight)
    expect(noisyWeight).toBeGreaterThanOrEqual(0.1)
  })

  test('buildConsensusRows ranks consistently strong models above models propped up by one noisy outlier', () => {
    const models = [
      model(1, 'consistent-strong', {}, true),
      model(2, 'noisy-outlier'),
      model(3, 'weak-baseline'),
    ]
    const benchmarks = [
      benchmark(STABLE_A, [
        [1, 100],
        [2, 90],
        [3, 80],
      ]),
      benchmark(STABLE_B, [
        [1, 98],
        [2, 88],
        [3, 78],
      ]),
      benchmark(NOISY_FLIP, [
        [2, 100],
        [3, 50],
        [1, 10],
      ]),
    ]

    const rows = buildRows(models, benchmarks, [STABLE_A, STABLE_B, NOISY_FLIP])
    const consistent = rowFor(rows, 'consistent-strong')
    const noisy = rowFor(rows, 'noisy-outlier')

    expect(consistent.consensusScore).toBeGreaterThan(noisy.consensusScore)
    expect(rows[0].modelSlug).toBe('consistent-strong')
    expect(consistent.openWeights).toBe(true)
    expect(noisy.openWeights).toBe(false)
  })

  test('buildConsensusRows includes lmarena_text_overall from model scores and lets it act as a perception anchor', () => {
    const models = [
      model(1, 'benchmark-only-leader', { [ARENA]: score(1000) }),
      model(2, 'arena-leader', { [ARENA]: score(1400) }),
      model(3, 'baseline', { [ARENA]: score(1100) }),
    ]
    const benchmarks = [
      benchmark(STABLE_A, [
        [1, 100],
        [2, 90],
        [3, 80],
      ]),
    ]

    const rows = buildRows(models, benchmarks, [STABLE_A, ARENA])
    const benchmarkOnlyLeader = rowFor(rows, 'benchmark-only-leader')
    const arenaLeader = rowFor(rows, 'arena-leader')

    expect(arenaLeader.scores[ARENA]).toMatchObject({
      score: 1400,
      percentile: 100,
    })
    expect(benchmarkOnlyLeader.scores[ARENA]).toMatchObject({
      score: 1000,
      percentile: 0,
    })
    expect(arenaLeader.consensusScore).toBeGreaterThan(benchmarkOnlyLeader.consensusScore)
    expect(rows[0].modelSlug).toBe('arena-leader')
  })

  test('disagreementScore remains the raw percentile standard deviation even when the outlier benchmark is downweighted', () => {
    const models = [
      model(1, 'volatile-leader'),
      model(2, 'noisy-outlier'),
      model(3, 'weak-baseline'),
    ]
    const benchmarks = [
      benchmark(STABLE_A, [
        [1, 100],
        [2, 90],
        [3, 80],
      ]),
      benchmark(STABLE_B, [
        [1, 98],
        [2, 88],
        [3, 78],
      ]),
      benchmark(NOISY_FLIP, [
        [2, 100],
        [3, 50],
        [1, 10],
      ]),
    ]

    const rows = buildRows(models, benchmarks, [STABLE_A, STABLE_B, NOISY_FLIP])
    const volatileLeader = rowFor(rows, 'volatile-leader')
    const rawPercentiles = [100, 100, 0]
    const rawAverage = rawPercentiles.reduce((sum, value) => sum + value, 0) / rawPercentiles.length
    const rawSampleStdev = Math.sqrt(
      rawPercentiles.reduce((sum, value) => sum + (value - rawAverage) ** 2, 0) / (rawPercentiles.length - 1),
    )

    expect(volatileLeader.consensusScore).toBeGreaterThan(rawAverage)
    expect(volatileLeader.disagreementScore).toBeCloseTo(rawSampleStdev, 5)
  })
})
