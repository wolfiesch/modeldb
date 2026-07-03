import { describe, expect, test } from 'bun:test'
import type { EloFile, Model } from './data'
import { buildTimelineRows } from './timelineRows'

function dateMs(date: string): number {
  return Date.parse(`${date}T00:00:00.000Z`)
}

function model(overrides: Partial<Model> & Pick<Model, 'id' | 'slug' | 'name' | 'released'>): Model {
  const base = {
    dev: 'test-lab',
    devName: 'Test Lab',
    family: null,
    generation: null,
    tier: null,
    params: null,
    role: null,
    cutoff: null,
    stability: 'stable',
    open: null,
    ctx: null,
    maxOut: null,
    inMod: null,
    outMod: null,
    priceIn: null,
    priceOut: null,
    priceCacheRead: null,
    priceCacheWrite: null,
    scores: {},
  } satisfies Omit<Model, 'id' | 'slug' | 'name' | 'released'>

  return {
    ...base,
    ...overrides,
    id: overrides.id,
    slug: overrides.slug,
    name: overrides.name,
    released: overrides.released,
  }
}

function eloPoint(modelId: number, date: string): EloFile['series'][number] {
  return {
    modelId,
    t: [dateMs(date)],
    elo: [1234],
    rank: [1],
  }
}

type TimelineRowForTest = {
  model: Model
  released: string
  observedThrough: string | null
  displayEnd?: string
  shownThrough?: string
  active: boolean
  retired: boolean
}

function onlyRow(rows: TimelineRowForTest[]): TimelineRowForTest {
  expect(rows).toHaveLength(1)
  return rows[0]
}

function displayEnd(row: TimelineRowForTest): string | undefined {
  return row.displayEnd ?? row.shownThrough
}

describe('timeline row derivation', () => {
  test('current models without ELO data show through the as-of date, not a synthetic 90-day future window', () => {
    const currentModel = model({
      id: 1,
      slug: 'current-no-elo',
      name: 'Current No ELO',
      released: '2026-06-30',
    })

    const row = onlyRow(buildTimelineRows([currentModel], [], dateMs('2026-07-02')) as TimelineRowForTest[])

    expect(row.released).toBe('2026-06-30')
    expect(row.observedThrough).toBeNull()
    expect(displayEnd(row)).toBe('2026-07-02')
    expect(displayEnd(row)).not.toBe('2026-09-28')
    expect(row.active).toBe(true)
    expect(row.retired).toBe(false)
  })

  test('current models preserve the last observed ELO date while displaying through the as-of date', () => {
    const currentModel = model({
      id: 2,
      slug: 'current-with-elo',
      name: 'Current With ELO',
      released: '2026-06-01',
    })

    const row = onlyRow(
      buildTimelineRows([currentModel], [eloPoint(currentModel.id, '2026-06-25')], dateMs('2026-07-02')) as TimelineRowForTest[],
    )

    expect(row.released).toBe('2026-06-01')
    expect(row.observedThrough).toBe('2026-06-25')
    expect(displayEnd(row)).toBe('2026-07-02')
    expect(row.active).toBe(true)
    expect(row.retired).toBe(false)
  })

  test('older stable models display through the as-of date even outside the recency window', () => {
    const olderStableModel = model({
      id: 5,
      slug: 'older-stable',
      name: 'Older Stable',
      released: '2026-01-01',
      stability: 'stable',
    })

    const row = onlyRow(
      buildTimelineRows([olderStableModel], [eloPoint(olderStableModel.id, '2026-02-01')], dateMs('2026-07-02')) as TimelineRowForTest[],
    )

    expect(row.released).toBe('2026-01-01')
    expect(row.observedThrough).toBe('2026-02-01')
    expect(row.displayEnd).toBe('2026-07-02')
    expect(row.shownThrough).toBe('2026-07-02')
    expect(row.active).toBe(true)
    expect(row.retired).toBe(false)
  })

  test('older models with missing stability stop at their last observed ELO date', () => {
    const olderModel = model({
      id: 4,
      slug: 'older-null-stability',
      name: 'Older Null Stability',
      released: '2024-04-20',
      stability: null,
    })

    const row = onlyRow(
      buildTimelineRows([olderModel], [eloPoint(olderModel.id, '2024-09-01')], dateMs('2026-07-02')) as TimelineRowForTest[],
    )

    expect(row.released).toBe('2024-04-20')
    expect(row.observedThrough).toBe('2024-09-01')
    expect(row.displayEnd).toBe('2024-09-01')
    expect(row.shownThrough).toBe('2024-09-01')
    expect(row.active).toBe(false)
    expect(row.retired).toBe(false)
  })

  test('retired models stop at their last observed ELO date instead of extending to the as-of date', () => {
    const retiredModel = model({
      id: 3,
      slug: 'retired-with-elo',
      name: 'Retired With ELO',
      released: '2026-05-01',
      stability: 'deprecated',
    })

    const row = onlyRow(
      buildTimelineRows([retiredModel], [eloPoint(retiredModel.id, '2026-06-20')], dateMs('2026-07-02')) as TimelineRowForTest[],
    )

    expect(row.released).toBe('2026-05-01')
    expect(row.observedThrough).toBe('2026-06-20')
    expect(displayEnd(row)).toBe('2026-06-20')
    expect(displayEnd(row)).not.toBe('2026-07-02')
    expect(row.active).toBe(false)
    expect(row.retired).toBe(true)
  })
})
