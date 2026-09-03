import { describe, expect, test } from 'bun:test'
import { benchmarkMetricKind, fmtBenchmarkScore } from './format'

describe('benchmark score formatting', () => {
  test('formats canonical percentage metrics as percentage points', () => {
    expect(fmtBenchmarkScore(69.3, 'percent_resolved')).toBe('69.3%')
    expect(fmtBenchmarkScore(92.6, 'accuracy')).toBe('92.6%')
    expect(fmtBenchmarkScore(0.17, 'percent')).toBe('0.2%')
  })

  test('does not infer units from score magnitude', () => {
    expect(fmtBenchmarkScore(0.3099, 'mean_score')).toBe('0.31')
    expect(fmtBenchmarkScore(61, 'index')).toBe('61.0')
    expect(fmtBenchmarkScore(1494, 'elo')).toBe('1,494')
  })

  test('normalizes metric spelling', () => {
    expect(benchmarkMetricKind('Percent correct')).toBe('percent')
    expect(benchmarkMetricKind('pass-rate')).toBe('percent')
  })
})
