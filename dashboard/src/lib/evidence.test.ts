import { describe, expect, test } from 'bun:test'
import type { Benchmark, BenchmarkResult } from './data'
import { buildEvidenceRows } from './evidence'

const benchmark: Benchmark = {
  id: 'benchmark',
  name: 'Benchmark',
  category: null,
  metricDefault: 'accuracy',
  higherIsBetter: 1,
  sourceUrl: null,
}

test('labels independently measured results and marks absent evidence unavailable', () => {
  const result: BenchmarkResult = {
    modelId: 1,
    score: 82.4,
    metric: null,
    rank: null,
    selfReported: 0,
    measuredAt: null,
  }

  const rows = buildEvidenceRows(benchmark, result)

  expect(rows).toContainEqual(['Reporting status', 'Independently reported'])
  expect(rows).toContainEqual(['Measured date', 'Unavailable'])
  expect(rows).toContainEqual(['Confidence interval', 'Unavailable'])
  expect(rows).toContainEqual(['Source URL', 'Unavailable'])
})

test('labels provider-reported results without inventing metadata', () => {
  const result: BenchmarkResult = {
    modelId: 1,
    score: 82.4,
    metric: 'pass@1',
    rank: 2,
    selfReported: 1,
    measuredAt: '2026-07-10',
    sourceId: 'provider',
    sourceName: 'Provider announcement',
    sourceUrl: 'https://example.com/announcement',
    sourceSnapshotId: 42,
    fetchedAt: '2026-07-11T00:00:00Z',
    ci: 1.2,
    votes: 100,
    evalCondition: { effort: 'high' },
    rawRecord: { result: 82.4 },
  }

  const rows = buildEvidenceRows(benchmark, result)

  expect(rows).toContainEqual(['Reporting status', 'Self-reported by provider'])
  expect(rows).toContainEqual(['Source name', 'Provider announcement'])
  expect(rows).toContainEqual(['Evaluation conditions', '{"effort":"high"}'])
  expect(rows).toContainEqual(['Raw record', '{"result":82.4}'])
})

describe('evidence field formatting', () => {
  test('uses benchmark metric only when a result metric is unavailable', () => {
    const rows = buildEvidenceRows(benchmark, {
      modelId: 1,
      score: 1,
      metric: null,
      rank: null,
      selfReported: 0,
      measuredAt: null,
    })

    expect(rows).toContainEqual(['Metric', 'accuracy'])
  })
})
