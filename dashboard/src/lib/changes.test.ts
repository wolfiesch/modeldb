import { describe, expect, test } from 'bun:test'
import { deriveChanges } from './data'
import type { ChangeObservation } from './data'

function observation(overrides: Partial<ChangeObservation> & Pick<ChangeObservation, 'kind' | 'entityId' | 'observedAt'>): ChangeObservation {
  return {
    kind: overrides.kind,
    entityId: overrides.entityId,
    observedAt: overrides.observedAt,
    sourceId: 'source-a',
    sourceUrl: 'https://example.com/source-a',
    snapshotId: 1,
    selfReported: null,
    evalCondition: null,
    before: null,
    after: null,
    ...overrides,
  }
}

describe('historical change derivation', () => {
  test('derives a model-added event from its first stored observation', () => {
    const events = deriveChanges([
      observation({ kind: 'model', entityId: 'openai/example', observedAt: '2026-01-03T00:00:00.000Z', after: { name: 'Example' } }),
    ])

    expect(events).toEqual([
      expect.objectContaining({
        category: 'model_added',
        entityId: 'openai/example',
        observedAt: '2026-01-03T00:00:00.000Z',
        before: null,
        after: { name: 'Example' },
      }),
    ])
  })

  test('derives benchmark score and rank changes between stored observations', () => {
    const events = deriveChanges([
      observation({
        kind: 'benchmark_result',
        entityId: 'gpqa:7',
        observedAt: '2026-01-01T00:00:00.000Z',
        before: null,
        after: { score: 61.2, rank: 4 },
      }),
      observation({
        kind: 'benchmark_result',
        entityId: 'gpqa:7',
        observedAt: '2026-01-05T00:00:00.000Z',
        after: { score: 66.4, rank: 2 },
      }),
    ])

    expect(events).toEqual([
      expect.objectContaining({
        category: 'benchmark_changed',
        entityId: 'gpqa:7',
        before: { score: 61.2, rank: 4 },
        after: { score: 66.4, rank: 2 },
      }),
    ])
  })

  test('omits observations whose comparable values did not change', () => {
    const events = deriveChanges([
      observation({ kind: 'benchmark_result', entityId: 'gpqa:7', observedAt: '2026-01-01T00:00:00.000Z', after: { score: 61.2, rank: 4 } }),
      observation({ kind: 'benchmark_result', entityId: 'gpqa:7', observedAt: '2026-01-05T00:00:00.000Z', after: { score: 61.2, rank: 4 } }),
    ])

    expect(events).toEqual([])
  })
})
