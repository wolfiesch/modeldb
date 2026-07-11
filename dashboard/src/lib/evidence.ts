import type { Benchmark, BenchmarkResult } from './data'

export type EvidenceRow = readonly [label: string, value: string]

function unavailable(value: unknown): string {
  if (value == null || value === '') return 'Unavailable'
  return String(value)
}

function serialized(value: unknown): string {
  if (value == null) return 'Unavailable'
  try {
    return JSON.stringify(value)
  } catch {
    return 'Unavailable'
  }
}

export function buildEvidenceRows(benchmark: Benchmark, result: BenchmarkResult): EvidenceRow[] {
  return [
    ['Source ID', unavailable(result.sourceId)],
    ['Source name', unavailable(result.sourceName)],
    ['Source URL', unavailable(result.sourceUrl)],
    ['Fetched timestamp', unavailable(result.fetchedAt)],
    ['Measured date', unavailable(result.measuredAt)],
    ['Snapshot ID', unavailable(result.sourceSnapshotId)],
    ['Metric', unavailable(result.metric ?? benchmark.metricDefault)],
    ['Confidence interval', unavailable(result.ci)],
    ['Votes', unavailable(result.votes)],
    ['Rank', unavailable(result.rank)],
    ['Reporting status', result.selfReported === 1 ? 'Self-reported by provider' : 'Independently reported'],
    ['Evaluation conditions', serialized(result.evalCondition)],
    ['Raw record', serialized(result.rawRecord)],
  ]
}
