import { describe, expect, test } from 'bun:test'
import { boundChangeFeed } from './change-feed.mjs'

describe('boundChangeFeed', () => {
  test('caps each category while preserving category totals', () => {
    const events = [
      ...Array.from({ length: 5 }, (_, index) => ({ category: 'benchmark_changed', observedAt: `2026-01-0${index + 1}` })),
      ...Array.from({ length: 3 }, (_, index) => ({ category: 'model_added', observedAt: `2026-02-0${index + 1}` })),
    ]

    const result = boundChangeFeed(events, 2)

    expect(result.events).toHaveLength(4)
    expect(result.totalEvents).toBe(8)
    expect(result.categoryTotals).toEqual({ benchmark_changed: 5, model_added: 3 })
    expect(result.truncated).toBe(true)
  })

  test('keeps newest events from each category in global date order', () => {
    const result = boundChangeFeed([
      { category: 'model_added', observedAt: '2026-01-01' },
      { category: 'model_added', observedAt: '2026-01-03' },
      { category: 'benchmark_changed', observedAt: '2026-01-02' },
    ], 1)

    expect(result.events.map((event) => event.observedAt)).toEqual(['2026-01-03', '2026-01-02'])
  })
})
