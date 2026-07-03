import { describe, expect, test } from 'bun:test'
import type { Enrichment, Model } from './data'
import { buildThroughputRows, coinPlanForThroughput } from './throughput'
import type { LocalThroughputRow, ThroughputFile } from './throughput'

function model(id: number, slug: string, name = `Model ${id}`): Model {
  return {
    id,
    slug,
    name,
    dev: `dev-${id}`,
    devName: `Developer ${id}`,
    family: null,
    generation: null,
    tier: null,
    params: null,
    role: null,
    released: null,
    cutoff: null,
    stability: null,
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
  }
}

function enrichmentEntry(modelId: number, tps: number | null): Enrichment[string] {
  return {
    modelId,
    artificialAnalysis: {},
    medianOutputTokensPerSecond:
      tps === null
        ? null
        : {
            value: tps,
            sourceSnapshotId: null,
            sourceId: 'artificial_analysis',
            fetchedAt: null,
          },
    medianTimeToFirstTokenSeconds: null,
    medianTimeToFirstAnswerToken: null,
    artificialAnalysisReleaseDate: null,
    vllm: {
      supported: null,
      architecture: null,
      backend: null,
    },
  }
}

function enrichment(rows: Array<[modelId: number, tps: number | null]>): Enrichment {
  return Object.fromEntries(rows.map(([modelId, tps]) => [String(modelId), enrichmentEntry(modelId, tps)]))
}

function localRow(overrides: Partial<LocalThroughputRow>): LocalThroughputRow {
  return {
    modelId: 1,
    canonicalSlug: 'openai/gpt-5.5',
    modelName: 'GPT 5.5',
    dev: 'openai',
    devName: 'OpenAI',
    providerLabel: 'OpenAI Codex',
    ompSelector: 'openai-codex/gpt-5.5:medium',
    tps: 123.4,
    visibleCharsPerSecond: null,
    durationMs: null,
    measuredAt: '2026-07-02T16:00:00.000Z',
    fetchedAt: null,
    sourceSnapshotId: null,
    artifactPath: null,
    sourceHash: null,
    runId: null,
    tokenizer: null,
    ...overrides,
  }
}


describe('throughput shaping', () => {
  test('buildThroughputRows prefers valid local OMP rows and keeps selector metadata', () => {
    const selector = 'openai-codex/gpt-5.5:medium'
    const providerLabel = 'OpenAI Codex'
    const local = {
      generatedAt: '2026-07-02T16:05:00.000Z',
      benchmarkId: 'omp_visible_output_tokens_per_second',
      rows: [localRow({ ompSelector: selector, providerLabel, tps: 123.4 })],
    } satisfies ThroughputFile
    const rows = buildThroughputRows(
      [model(1, 'openai/gpt-5.5', 'GPT 5.5'), model(2, 'google/gemini-3.1-pro', 'Gemini 3.1 Pro')],
      enrichment([
        [1, 99],
        [2, 80],
      ]),
      local,
    )

    expect(rows[0]).toMatchObject({
      source: 'local_omp',
      ompSelector: selector,
      providerLabel,
      tps: 123.4,
    })
  })

  test('buildThroughputRows drops zero and missing TPS values and sorts descending', () => {
    const models = [
      model(1, 'zero-model'),
      model(2, 'fast-model'),
      model(3, 'slow-model'),
      model(4, 'missing-model'),
    ]

    const rows = buildThroughputRows(
      models,
      enrichment([
        [1, 0],
        [2, 200],
        [3, 50],
      ]),
      null,
    )

    expect(rows.map((row) => row.tps)).toEqual([200, 50])
    expect(rows.map((row) => row.slug)).not.toContain('zero-model')
    expect(rows.map((row) => row.slug)).not.toContain('missing-model')
  })

  test('buildThroughputRows honors source filters', () => {
    const models = [model(1, 'local-model'), model(2, 'aa-model')]
    const aaEnrichment = enrichment([[2, 90]])
    const local = {
      generatedAt: '2026-07-02T16:05:00.000Z',
      benchmarkId: 'omp_visible_output_tokens_per_second',
      rows: [localRow({ modelId: 1, canonicalSlug: 'local-model', modelName: 'Local Model', tps: 120 })],
    } satisfies ThroughputFile

    const localRows = buildThroughputRows(models, aaEnrichment, local, { source: 'local_omp' })
    const artificialAnalysisRows = buildThroughputRows(models, aaEnrichment, local, { source: 'artificialanalysis' })
    const defaultRows = buildThroughputRows(models, aaEnrichment, local)

    expect(localRows.map((row) => row.source)).toEqual(['local_omp'])
    expect(artificialAnalysisRows.map((row) => row.source)).toEqual(['artificialanalysis'])
    expect(defaultRows.map((row) => row.source)).toEqual(['local_omp', 'artificialanalysis'])
  })

  test('coinPlanForThroughput keeps visible flux linear in TPS', () => {
    const oneHundred = coinPlanForThroughput(100)
    const fourHundred = coinPlanForThroughput(400)
    const twoSeventy = coinPlanForThroughput(270)
    const nineSixtyEight = coinPlanForThroughput(968)

    expect(coinPlanForThroughput(1).count).toBe(6)
    expect(coinPlanForThroughput(1000).count).toBe(600)
    expect(fourHundred.count).toBeCloseTo(oneHundred.count * 4, 0)
    expect(nineSixtyEight.count).toBeGreaterThanOrEqual(twoSeventy.count * 3)
    expect(fourHundred.fallSpeed).toBe(oneHundred.fallSpeed)
    expect(fourHundred.coinsPerSecond).toBeGreaterThan(oneHundred.coinsPerSecond)
    expect(coinPlanForThroughput(Number.NaN).coinsPerSecond).toBe(0)
  })
})
