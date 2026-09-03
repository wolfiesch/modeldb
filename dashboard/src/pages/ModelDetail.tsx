import { useMemo } from 'react'
import { Link, useParams } from 'react-router'
import {
  loadAliases,
  loadBenchmarks,
  loadEnrichment,
  loadElo,
  loadMeta,
  loadModels,
  loadPrices,
  loadRunOptions,
  useData,
} from '../lib/data'
import { LabLogo } from '../components/LabLogo'
import { EvidenceInspector } from '../components/EvidenceInspector'
import { labLabel } from '../lib/labs'
import { colorForDark, shortName } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import { useModelDrawer } from '../components/ModelDrawer'
import { fmtBenchmarkScore, fmtDate, fmtElo, fmtPrice, fmtTokens } from '../lib/format'
import type { EChartsCoreOption } from 'echarts/core'
import type { Benchmark, BenchmarkResult, Model, RunOptionPrice, RunOptionVariant } from '../lib/data'

const loadOverall = () => loadElo('text_overall')
const loadCoding = () => loadElo('text_coding')

const artificialAnalysisLabels = [
  ['artificial_analysis_intelligence_index', 'Intelligence'],
  ['artificial_analysis_coding_index', 'Coding'],
  ['artificial_analysis_math_index', 'Math'],
  ['mmlu_pro', 'MMLU-Pro'],
  ['gpqa', 'GPQA'],
  ['hle', 'HLE'],
  ['livecodebench', 'LiveCodeBench'],
  ['aime', 'AIME'],
  ['aime_25', 'AIME 2025'],
  ['math_500', 'MATH-500'],
  ['ifbench', 'IFBench'],
  ['lcr', 'LCR'],
  ['scicode', 'SciCode'],
  ['tau2', 'Tau2'],
  ['tau_banking', 'Tau Banking'],
  ['terminalbench_hard', 'Terminal-Bench Hard'],
  ['terminalbench_v2_1', 'Terminal-Bench v2.1'],
] as const

function formatTokenBudget(value: number | null) {
  return value == null ? 'n/a' : value.toLocaleString()
}

function formatRunPrice(price: RunOptionPrice | undefined) {
  if (!price) return 'n/a'
  if (price.usdPer1m != null) return `$${price.usdPer1m.toLocaleString(undefined, { maximumFractionDigits: 6 })}`
  return `${price.amount} / ${price.unit}`
}

function priceFor(prices: RunOptionPrice[], component: string) {
  return prices
    .filter((price) => price.component === component)
    .toSorted((a, b) => (a.usdPer1m ?? Number.POSITIVE_INFINITY) - (b.usdPer1m ?? Number.POSITIVE_INFINITY))[0]
}

function lowestPriceFor(surfaces: Array<{ prices: RunOptionPrice[] }>, component: string) {
  const values = surfaces
    .map((surface) => priceFor(surface.prices, component)?.usdPer1m ?? null)
    .filter((value): value is number => value != null)
  return values.length === 0 ? null : Math.min(...values)
}

function priceCellClass(value: number | null, lowest: number | null) {
  return value != null && lowest != null && value === lowest
    ? 'px-2 py-1.5 text-right font-semibold text-emerald-300'
    : 'px-2 py-1.5 text-right text-neutral-300'
}

function routeBadge(surfaceType: string | null, providerId: string) {
  const route = (surfaceType ?? providerId).toLowerCase()
  if (route.includes('openrouter') || providerId === 'openrouter') {
    return { label: 'OpenRouter', className: 'border-purple-500/40 bg-purple-500/10 text-purple-200' }
  }
  if (route.includes('bedrock') || providerId.includes('bedrock')) {
    return { label: 'Bedrock', className: 'border-amber-500/40 bg-amber-500/10 text-amber-200' }
  }
  if (route.includes('vertex') || providerId.includes('vertex')) {
    return { label: 'Vertex', className: 'border-sky-500/40 bg-sky-500/10 text-sky-200' }
  }
  if (route.includes('azure') || providerId.includes('azure')) {
    return { label: 'Azure', className: 'border-blue-500/40 bg-blue-500/10 text-blue-200' }
  }
  if (route.includes('first')) {
    return { label: 'First-party API', className: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200' }
  }
  return {
    label: surfaceType?.replaceAll('_', ' ') ?? 'Hosted route',
    className: 'border-neutral-700 bg-neutral-800/70 text-neutral-300',
  }
}

function capabilityBadgeClass(enabled: boolean | null) {
  if (enabled === true) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  if (enabled === false) return 'border-neutral-700 bg-neutral-950 text-neutral-500'
  return 'border-neutral-700 bg-neutral-950 text-neutral-600'
}

function formatFreshnessDate(value: string | null | undefined) {
  if (!value) return 'n/a'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

function repoHref(artifactRef: string) {
  return artifactRef.includes('/') ? `https://huggingface.co/${artifactRef}` : null
}

function variantSummary(variant: RunOptionVariant) {
  const parts = [variant.quantization, variant.format, variant.parameterCount?.toLocaleString()].filter(
    Boolean,
  )
  return parts.length === 0 ? variant.filePattern ?? 'variant' : parts.join(' · ')
}

function hasModality(modalities: string[], modality: string) {
  const needle = modality.toLowerCase()
  return modalities.some((entry) => entry.toLowerCase().includes(needle))
}

function evidenceResult(benchmark: Benchmark, modelId: number, score: BenchmarkResult): BenchmarkResult {
  return benchmark.results?.filter((result) => result.modelId === modelId).at(-1) ?? score
}

export default function ModelDetail() {
  const { slug = '' } = useParams()
  const { data: models, loading, error } = useData(loadModels)
  const { data: benchmarks } = useData(loadBenchmarks)
  const { data: prices } = useData(loadPrices)
  const { data: aliases } = useData(loadAliases)
  const { data: eloOverall } = useData(loadOverall)
  const { data: eloCoding } = useData(loadCoding)
  const { data: runOptions } = useData(loadRunOptions)
  const { data: enrichment } = useData(loadEnrichment)
  const { data: meta } = useData(loadMeta)

  const model = useMemo(
    () => models?.find((m) => m.slug === decodeURIComponent(slug)) ?? null,
    [models, slug],
  )

  const { openModel } = useModelDrawer()

  const eloOption = useMemo<EChartsCoreOption | null>(() => {
    if (!model) return null
    const series = []
    for (const [label, file] of [
      ['text overall', eloOverall],
      ['text coding', eloCoding],
    ] as const) {
      const s = file?.series.find((x) => x.modelId === model.id)
      if (!s) continue
      series.push({
        name: label,
        type: 'line',
        showSymbol: false,
        data: s.t.map((t, i) => [t, s.elo[i]]),
        lineStyle: { width: 2 },
      })
    }
    if (series.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 24, top: 32, bottom: 40 },
      legend: { textStyle: { color: '#a3a3a3' }, top: 0 },
      xAxis: {
        type: 'time',
        axisLabel: { color: '#a3a3a3' },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLabel: { color: '#a3a3a3' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      tooltip: { trigger: 'axis' },
      color: [colorForDark(model.dev), '#eab308'],
      series,
    }
  }, [model, eloOverall, eloCoding])

  const chartRef = useECharts(eloOption)

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
        <div className="mb-2 text-lg text-neutral-200">Failed to load model data</div>
        <div className="mb-4 text-sm text-red-400">{error}</div>
        <button
          onClick={() => window.location.reload()}
          className="rounded-full border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:border-neutral-500"
        >
          Retry
        </button>
      </div>
    )
  }
  if (!model) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
        <div className="mb-2 text-lg text-neutral-200">Model not found</div>
        <div className="mb-4 text-sm text-neutral-500">
          No model with slug “{decodeURIComponent(slug)}”.
        </div>
        <Link to="/models" className="text-sm text-blue-400 hover:underline">
          ← Back to Model Explorer
        </Link>
      </div>
    )
  }

  const modelPrices = prices?.find((p) => p.modelId === model.id)?.rows ?? []
  const modelAliases = (aliases ?? []).filter((a) => a.modelId === model.id)
  const modelRunOptions = runOptions?.find((item) => item.modelId === model.id) ?? {
    modelId: model.id,
    surfaces: [],
    artifacts: [],
  }
  const surfaceInputFloor = lowestPriceFor(modelRunOptions.surfaces, 'input_token')
  const surfaceOutputFloor = lowestPriceFor(modelRunOptions.surfaces, 'output_token')
  const latestSnapshotBySource = new Map<string, { sourceName: string; fetchedAt: string }>()
  for (const snapshot of meta?.snapshots ?? []) {
    const current = latestSnapshotBySource.get(snapshot.sourceId)
    if (!current || snapshot.fetchedAt > current.fetchedAt) {
      latestSnapshotBySource.set(snapshot.sourceId, {
        sourceName: snapshot.sourceName,
        fetchedAt: snapshot.fetchedAt,
      })
    }
  }
  const modelModalities = [...(model.inMod ?? []), ...(model.outMod ?? [])]
  const aliasesBySource = new Map<string, typeof modelAliases>()
  for (const a of modelAliases) {
    const list = aliasesBySource.get(a.sourceId) ?? []
    list.push(a)
    aliasesBySource.set(a.sourceId, list)
  }

  const benchById = new Map((benchmarks ?? []).map((b) => [b.id, b]))
  const scoreEntries = Object.entries(model.scores).sort(
    (a, b) => (b[1].score ?? 0) - (a[1].score ?? 0),
  )
  const capabilityRows = scoreEntries
    .filter(([id]) => !id.startsWith('lmarena_') && (benchById.get(id)?.higherIsBetter ?? 1) === 1)
    .map(([id, s]) => {
      const score = s.score ?? 0
      const metric = s.metric ?? benchById.get(id)?.metricDefault
      const width = score <= 100 ? score : 0
      return {
        id,
        name: benchById.get(id)?.name ?? id,
        score,
        metric,
        width: `${Math.max(0, Math.min(100, width))}%`,
      }
    })
    .filter((row) => row.score > 0)
    .sort((a, b) => Number.parseFloat(b.width) - Number.parseFloat(a.width))
    .slice(0, 6)
  const currentElo = model.scores.lmarena_text_overall?.score ?? null
  const currentOutputPrice = model.priceOut
  const alternativeCandidates: Array<{ label: string; model: Model }> = []
  if (models) {
    if (currentElo != null && currentOutputPrice != null) {
      const cheaperSimilar = models
        .filter(
          (m) =>
            m.id !== model.id &&
            m.priceOut != null &&
            m.priceOut < currentOutputPrice &&
            m.scores.lmarena_text_overall?.score != null &&
            Math.abs(m.scores.lmarena_text_overall.score - currentElo) <= 30,
        )
        .toSorted(
          (a, b) =>
            Math.abs((a.scores.lmarena_text_overall?.score ?? 0) - currentElo) -
            Math.abs((b.scores.lmarena_text_overall?.score ?? 0) - currentElo) ||
            (a.priceOut ?? Number.POSITIVE_INFINITY) - (b.priceOut ?? Number.POSITIVE_INFINITY),
        )[0]
      if (cheaperSimilar) alternativeCandidates.push({ label: 'Cheaper, similar quality', model: cheaperSimilar })
    }

    const openWeightAlternative = models
      .filter(
        (m) =>
          m.id !== model.id &&
          m.open === 1 &&
          m.scores.lmarena_text_overall?.score != null &&
          (model.open !== 1 || currentElo == null || m.scores.lmarena_text_overall.score > currentElo),
      )
      .toSorted(
        (a, b) => (b.scores.lmarena_text_overall?.score ?? -Infinity) - (a.scores.lmarena_text_overall?.score ?? -Infinity),
      )[0]
    if (openWeightAlternative) alternativeCandidates.push({ label: 'Open-weight alternative', model: openWeightAlternative })

    if (model.released && model.family != null) {
      const releaseTime = new Date(model.released).getTime()
      if (!Number.isNaN(releaseTime)) {
        const sibling = models
          .filter(
            (m) =>
              m.id !== model.id &&
              m.dev === model.dev &&
              m.family === model.family &&
              m.released != null &&
              m.released !== model.released &&
              !Number.isNaN(new Date(m.released).getTime()),
          )
          .toSorted(
            (a, b) =>
              Math.abs(new Date(a.released!).getTime() - releaseTime) -
              Math.abs(new Date(b.released!).getTime() - releaseTime),
          )[0]
        if (sibling) alternativeCandidates.push({ label: 'Same developer, newer/older', model: sibling })
      }
    }

    if (currentElo != null) {
      const higherQuality = models
        .filter(
          (m) =>
            m.id !== model.id &&
            m.scores.lmarena_text_overall?.score != null &&
            m.scores.lmarena_text_overall.score > currentElo,
        )
        .toSorted(
          (a, b) => (a.scores.lmarena_text_overall?.score ?? Infinity) - (b.scores.lmarena_text_overall?.score ?? Infinity),
        )[0]
      if (higherQuality) alternativeCandidates.push({ label: 'Higher quality', model: higherQuality })
    }
  }
  const seenAlternativeSlugs = new Set<string>()
  const alternatives = alternativeCandidates.filter(({ model: candidate }) => {
    if (seenAlternativeSlugs.has(candidate.slug)) return false
    seenAlternativeSlugs.add(candidate.slug)
    return true
  })
  const modelEnrichment = enrichment?.[String(model.id)] ?? null
  const artificialRows = artificialAnalysisLabels
    .map(([id, label]) => ({ id, label, signal: modelEnrichment?.artificialAnalysis[id] ?? null }))
    .filter((row) => row.signal)
  const vllmRows: Array<[string, string]> = []
  if (modelEnrichment?.vllm.supported) {
    vllmRows.push(['Supported', modelEnrichment.vllm.supported.value === true ? 'yes' : 'no'])
  }
  if (modelEnrichment?.vllm.architecture) {
    vllmRows.push(['Architecture', String(modelEnrichment.vllm.architecture.value)])
  }
  if (modelEnrichment?.vllm.backend) {
    vllmRows.push(['Backend', String(modelEnrichment.vllm.backend.value)])
  }
  const hasEnrichmentSignals =
    artificialRows.length > 0 ||
    modelEnrichment?.medianOutputTokensPerSecond != null ||
    modelEnrichment?.medianTimeToFirstTokenSeconds != null ||
    modelEnrichment?.medianTimeToFirstAnswerToken != null ||
    modelEnrichment?.artificialAnalysisReleaseDate != null ||
    vllmRows.length > 0

  const specs: Array<[string, string]> = [
    ['Slug', model.slug],
    ['Developer', labLabel(model.dev, model.devName)],
    ['Family', model.family ?? '—'],
    ['Generation', model.generation ?? '—'],
    ['Tier / variant', model.tier ?? '—'],
    ['Parameters', model.params ?? '—'],
    ['Training role', model.role ?? '—'],
    ['Released', fmtDate(model.released)],
    ['Knowledge cutoff', fmtDate(model.cutoff)],
    ['Stability', model.stability ?? '—'],
    ['Open weights', model.open === 1 ? 'yes' : model.open === 0 ? 'no' : '—'],
    ['LMArena ELO', fmtElo(currentElo)],
    ['Context window', fmtTokens(model.ctx)],
    ['Max output', fmtTokens(model.maxOut)],
    ['Input modalities', model.inMod?.join(', ') ?? '—'],
    ['Output modalities', model.outMod?.join(', ') ?? '—'],
    ['$ in / 1M', fmtPrice(model.priceIn)],
    ['$ out / 1M', fmtPrice(model.priceOut)],
    ['$ cache read / 1M', fmtPrice(model.priceCacheRead)],
    ['$ cache write / 1M', fmtPrice(model.priceCacheWrite)],
  ]

  return (
    <div className="space-y-6">
      <div>
        <Link to="/models" className="text-xs text-neutral-500 hover:text-neutral-300">
          ← Model Explorer
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="flex min-w-0 items-center gap-3 text-2xl font-bold text-neutral-100">
            <LabLogo
              dev={model.dev}
              devName={model.devName}
              size={30}
              decorative
              imgClassName="rounded-md"
            />
            <span className="truncate">{model.name}</span>
          </h1>
          <Link
            to={`/compare?a=${encodeURIComponent(model.slug)}`}
            className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-neutral-500"
          >
            Compare
          </Link>
        </div>
        <div className="text-sm text-neutral-500">{model.slug}</div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-3 text-sm font-semibold text-neutral-200">Specs</h2>
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
            {specs.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-neutral-500">{k}</dt>
                <dd className="text-neutral-200">
                  {k === 'Developer' && model.dev ? (
                    <Link to={`/devs/${model.dev}`} className="text-blue-400 hover:underline">
                      <LabLogo dev={model.dev} devName={model.devName} size={18} showLabel />
                    </Link>
                  ) : (
                    v
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="space-y-6">
          {capabilityRows.length > 0 ? (
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <div className="mb-3">
                <h2 className="text-sm font-semibold text-neutral-200">Capability profile</h2>
                <p className="mt-1 text-xs text-neutral-500">
                  Strongest recorded benchmark signals for this model.
                </p>
              </div>
              <div className="space-y-3">
                {capabilityRows.map((row) => (
                  <div key={row.id}>
                    <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                      <span className="truncate text-neutral-300">{row.name}</span>
                      <span className="font-medium text-neutral-100">
                        {fmtBenchmarkScore(row.score, row.metric)}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-neutral-800">
                      <div
                        className="h-2 rounded-full bg-cyan-400/80"
                        style={{ width: row.width }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <h2 className="mb-3 text-sm font-semibold text-neutral-200">Arena ELO history</h2>
            {eloOption ? (
              <div ref={chartRef} className="h-64 w-full" />
            ) : (
              <div className="py-10 text-center text-sm text-neutral-500">
                No LMArena history for this model.
              </div>
            )}
          </div>

          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <h2 className="mb-3 text-sm font-semibold text-neutral-200">Benchmark scores</h2>
            {scoreEntries.length === 0 ? (
              <div className="py-6 text-center text-sm text-neutral-500">No scores.</div>
            ) : (
              <table className="w-full text-sm">
                <tbody>
                  {scoreEntries.map(([id, s]) => {
                    const benchmark = benchById.get(id) ?? {
                      id,
                      name: id,
                      category: null,
                      metricDefault: null,
                      higherIsBetter: 1,
                      sourceUrl: null,
                    }
                    const score: BenchmarkResult = {
                      modelId: model.id,
                      score: s.score,
                      metric: s.metric,
                      rank: s.rank,
                      selfReported: s.selfReported,
                      measuredAt: s.measuredAt,
                    }
                    const displayScore = fmtBenchmarkScore(s.score, s.metric ?? benchmark.metricDefault)
                    return (
                      <tr key={id} className="border-t border-neutral-800/60 first:border-t-0">
                        <td className="py-1.5 text-neutral-300">{benchmark.name}</td>
                        <td className="py-1.5 text-right">
                          <EvidenceInspector
                            benchmark={benchmark}
                            result={evidenceResult(benchmark, model.id, score)}
                            label={displayScore}
                          />
                        </td>
                        <td className="w-24 py-1.5 pl-3 text-right">
                          {s.selfReported === 1 && (
                            <span className="rounded bg-amber-950 px-1.5 py-0.5 text-[10px] text-amber-400">
                              self-reported
                            </span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <h2 className="mb-3 text-sm font-semibold text-neutral-200">Enrichment signals</h2>
            {!hasEnrichmentSignals ? (
              <div className="py-6 text-center text-sm text-neutral-500">
                No enrichment signals are recorded yet.
              </div>
            ) : (
              <div className="space-y-4 text-sm">
                {artificialRows.length > 0 ? (
                  <div>
                    <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                      Artificial Analysis
                    </h3>
                    <table className="w-full">
                      <tbody>
                        {artificialRows.map(({ id, label, signal }) =>
                          signal ? (
                            <tr key={id} className="border-t border-neutral-800/60 first:border-t-0">
                              <td className="py-1.5 text-neutral-300">{label}</td>
                              <td className="py-1.5 text-right text-neutral-100">
                                {fmtBenchmarkScore(signal.score, signal.metric)}
                              </td>
                            </tr>
                          ) : null,
                        )}
                      </tbody>
                    </table>
                  </div>
                ) : null}

                {modelEnrichment?.medianOutputTokensPerSecond ||
                  modelEnrichment?.medianTimeToFirstTokenSeconds ||
                  modelEnrichment?.medianTimeToFirstAnswerToken ||
                  modelEnrichment?.artificialAnalysisReleaseDate ? (
                  <div>
                    <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                      Speed
                    </h3>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
                      {modelEnrichment?.medianOutputTokensPerSecond ? (
                        <div className="contents">
                          <dt className="text-neutral-500">Output tokens/sec</dt>
                          <dd className="text-right text-neutral-200">
                            {Number(modelEnrichment.medianOutputTokensPerSecond.value).toLocaleString(
                              undefined,
                              { maximumFractionDigits: 1 },
                            )}
                          </dd>
                        </div>
                      ) : null}
                      {modelEnrichment?.medianTimeToFirstTokenSeconds ? (
                        <div className="contents">
                          <dt className="text-neutral-500">TTFT</dt>
                          <dd className="text-right text-neutral-200">
                            {Number(modelEnrichment.medianTimeToFirstTokenSeconds.value).toLocaleString(
                              undefined,
                              { maximumFractionDigits: 2 },
                            )}
                            s
                          </dd>
                        </div>
                      ) : null}
                      {modelEnrichment?.medianTimeToFirstAnswerToken ? (
                        <div className="contents">
                          <dt className="text-neutral-500">TTFA</dt>
                          <dd className="text-right text-neutral-200">
                            {Number(modelEnrichment.medianTimeToFirstAnswerToken.value).toLocaleString(
                              undefined,
                              { maximumFractionDigits: 2 },
                            )}
                            s
                          </dd>
                        </div>
                      ) : null}
                      {modelEnrichment?.artificialAnalysisReleaseDate ? (
                        <div className="contents">
                          <dt className="text-neutral-500">AA release</dt>
                          <dd className="text-right text-neutral-200">
                            {String(modelEnrichment.artificialAnalysisReleaseDate.value)}
                          </dd>
                        </div>
                      ) : null}
                    </dl>
                  </div>
                ) : null}

                {vllmRows.length > 0 ? (
                  <div>
                    <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                      vLLM
                    </h3>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1">
                      {vllmRows.map(([label, value]) => (
                        <div key={label} className="contents">
                          <dt className="text-neutral-500">{label}</dt>
                          <dd className="text-right text-neutral-200">{value}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>

      {alternatives.length > 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <div className="mb-4">
            <h2 className="text-sm font-semibold text-neutral-200">Alternatives</h2>
            <p className="mt-1 text-xs text-neutral-500">
              Nearby choices from the current model catalog.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {alternatives.map(({ label, model: alternative }) => (
              <button
                key={`${label}:${alternative.slug}`}
                type="button"
                onClick={() => openModel(alternative.slug)}
                className="rounded-lg border border-neutral-800 bg-neutral-950/60 p-3 text-left transition hover:border-cyan-500/50 hover:bg-neutral-900"
              >
                <div className="mb-3 text-[10px] font-medium uppercase tracking-wide text-cyan-300">
                  {label}
                </div>
                <div className="flex items-center gap-2">
                  <LabLogo
                    dev={alternative.dev}
                    devName={alternative.devName}
                    size={22}
                    decorative
                    imgClassName="rounded"
                  />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-neutral-100">
                      {shortName(alternative.slug)}
                    </div>
                    <div className="truncate text-xs text-neutral-500">
                      {labLabel(alternative.dev, alternative.devName)}
                    </div>
                  </div>
                </div>
                <div className="mt-3 flex items-center justify-between gap-3 text-xs">
                  <span className="text-neutral-500">ELO</span>
                  <span className="font-medium text-neutral-200">
                    {fmtElo(alternative.scores.lmarena_text_overall?.score)}
                  </span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-3 text-xs">
                  <span className="text-neutral-500">Output</span>
                  <span className="font-medium text-neutral-200">{fmtPrice(alternative.priceOut)}</span>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-neutral-200">Where can I run it?</h2>
          <p className="mt-1 text-xs text-neutral-500">
            Hosted endpoints and local weight artifacts linked to this canonical model.
          </p>
        </div>

        {modelRunOptions.surfaces.length === 0 && modelRunOptions.artifacts.length === 0 ? (
          <div className="rounded-md border border-neutral-800 bg-neutral-950/50 py-8 text-center text-sm text-neutral-500">
            No hosted API surfaces or local weights are recorded yet.
          </div>
        ) : (
          <div className="space-y-5">
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                Hosted API surfaces
              </h3>
              {modelRunOptions.surfaces.length === 0 ? (
                <div className="rounded-md border border-neutral-800 bg-neutral-950/50 py-5 text-center text-sm text-neutral-500">
                  No hosted API surfaces.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1180px] text-sm">
                    <thead className="text-left text-xs text-neutral-500">
                      <tr>
                        <th className="px-2 py-1.5 font-medium">Provider</th>
                        <th className="px-2 py-1.5 font-medium">Route map</th>
                        <th className="px-2 py-1.5 font-medium">Endpoint model id</th>
                        <th className="px-2 py-1.5 font-medium">Capabilities</th>
                        <th className="px-2 py-1.5 font-medium">Modalities</th>
                        <th className="px-2 py-1.5 text-right font-medium">Context</th>
                        <th className="px-2 py-1.5 text-right font-medium">Max output</th>
                        <th className="px-2 py-1.5 text-right font-medium">Input $/1M</th>
                        <th className="px-2 py-1.5 text-right font-medium">Output $/1M</th>
                        <th className="px-2 py-1.5 font-medium">Cost freshness</th>
                      </tr>
                    </thead>
                    <tbody>
                      {modelRunOptions.surfaces.map((surface, i) => {
                        const inputPrice = priceFor(surface.prices, 'input_token')
                        const outputPrice = priceFor(surface.prices, 'output_token')
                        const route = routeBadge(surface.surfaceType, surface.providerId)
                        const supportsCaching = surface.prices.some((price) => price.component.startsWith('cache_'))
                        const sourceIds = Array.from(
                          new Set(
                            [surface.sourceId, ...surface.prices.map((price) => price.sourceId)].filter(
                              (sourceId): sourceId is string => sourceId != null,
                            ),
                          ),
                        )
                        return (
                          <tr key={`${surface.providerId}:${surface.endpointModelId}:${i}`} className="border-t border-neutral-800/60 align-top">
                            <td className="px-2 py-2 text-neutral-200">
                              <div className="font-medium">{surface.providerId}</div>
                              {surface.region ? (
                                <div className="text-[10px] uppercase tracking-wide text-neutral-600">{surface.region}</div>
                              ) : null}
                            </td>
                            <td className="px-2 py-2 text-neutral-300">
                              <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide ${route.className}`}>
                                {route.label}
                              </span>
                              {surface.openWeights === true ? (
                                <span className="ml-1 inline-flex rounded-full border border-neutral-700 bg-neutral-950 px-2 py-0.5 text-[10px] uppercase tracking-wide text-neutral-400">
                                  open weights
                                </span>
                              ) : null}
                            </td>
                            <td className="px-2 py-2 text-neutral-300">
                              <code className="text-xs">{surface.endpointModelId}</code>
                            </td>
                            <td className="px-2 py-2">
                              <div className="flex flex-wrap gap-1">
                                {(
                                  [
                                    ['Tool choice', surface.toolCall],
                                    ['Reasoning', surface.reasoning],
                                    ['Caching', supportsCaching],
                                  ] satisfies Array<[string, boolean | null]>
                                ).map(([label, enabled]) => (
                                  <span key={label} className={`rounded-full border px-2 py-0.5 text-[10px] ${capabilityBadgeClass(enabled)}`}>
                                    {label}
                                  </span>
                                ))}
                              </div>
                            </td>
                            <td className="px-2 py-2">
                              <div className="flex flex-wrap gap-1">
                                {['Text', 'Image', 'PDF', 'Audio', 'Video'].map((modality) => {
                                  const enabled = hasModality(modelModalities, modality)
                                  return (
                                    <span key={modality} className={`rounded-full border px-2 py-0.5 text-[10px] ${capabilityBadgeClass(enabled)}`}>
                                      {modality}
                                    </span>
                                  )
                                })}
                              </div>
                            </td>
                            <td className="px-2 py-2 text-right text-neutral-300">
                              {formatTokenBudget(surface.contextWindow)}
                            </td>
                            <td className="px-2 py-2 text-right text-neutral-300">
                              {formatTokenBudget(surface.maxOutput)}
                            </td>
                            <td className={priceCellClass(inputPrice?.usdPer1m ?? null, surfaceInputFloor)}>
                              {formatRunPrice(inputPrice)}
                            </td>
                            <td className={priceCellClass(outputPrice?.usdPer1m ?? null, surfaceOutputFloor)}>
                              {formatRunPrice(outputPrice)}
                            </td>
                            <td className="px-2 py-2 text-xs text-neutral-400">
                              {sourceIds.length === 0 ? (
                                'n/a'
                              ) : (
                                <ul className="space-y-1">
                                  {sourceIds.map((sourceId) => {
                                    const snapshot = latestSnapshotBySource.get(sourceId)
                                    return (
                                      <li key={sourceId}>
                                        <span className="text-neutral-300">{snapshot?.sourceName ?? sourceId}</span>
                                        <span className="ml-1 text-neutral-600">
                                          {formatFreshnessDate(snapshot?.fetchedAt)}
                                        </span>
                                      </li>
                                    )
                                  })}
                                </ul>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-neutral-500">
                Local weights
              </h3>
              {modelRunOptions.artifacts.length === 0 ? (
                <div className="rounded-md border border-neutral-800 bg-neutral-950/50 py-5 text-center text-sm text-neutral-500">
                  No local weight artifacts.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-neutral-500">
                      <tr>
                        <th className="px-2 py-1.5 font-medium">Repository</th>
                        <th className="px-2 py-1.5 font-medium">License</th>
                        <th className="px-2 py-1.5 font-medium">Gated</th>
                        <th className="px-2 py-1.5 font-medium">SHA</th>
                        <th className="px-2 py-1.5 font-medium">Last modified</th>
                        <th className="px-2 py-1.5 font-medium">Variants</th>
                      </tr>
                    </thead>
                    <tbody>
                      {modelRunOptions.artifacts.map((artifact) => {
                        const href = repoHref(artifact.artifactRef)
                        return (
                          <tr key={`${artifact.sourceId ?? 'artifact'}:${artifact.artifactRef}`} className="border-t border-neutral-800/60 align-top">
                            <td className="px-2 py-1.5 text-neutral-200">
                              {href ? (
                                <a href={href} className="text-blue-400 hover:underline" target="_blank" rel="noreferrer">
                                  {artifact.artifactRef}
                                </a>
                              ) : (
                                artifact.artifactRef
                              )}
                              {artifact.artifactType ? (
                                <div className="text-[10px] text-neutral-600">{artifact.artifactType}</div>
                              ) : null}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-400">{artifact.license ?? 'n/a'}</td>
                            <td className="px-2 py-1.5 text-neutral-400">{artifact.gated ?? 'n/a'}</td>
                            <td className="px-2 py-1.5 text-neutral-400">
                              {artifact.sha ? <code className="text-xs">{artifact.sha.slice(0, 12)}</code> : 'n/a'}
                            </td>
                            <td className="px-2 py-1.5 text-neutral-400">{artifact.lastModified ?? 'n/a'}</td>
                            <td className="px-2 py-1.5 text-neutral-300">
                              {artifact.variants.length === 0 ? (
                                'n/a'
                              ) : (
                                <ul className="space-y-1">
                                  {artifact.variants.slice(0, 3).map((variant, i) => (
                                    <li key={`${variant.filePattern ?? variantSummary(variant)}:${i}`}>
                                      {variantSummary(variant)}
                                      {variant.sizeBytes != null ? (
                                        <span className="ml-1 text-[10px] text-neutral-600">
                                          {variant.sizeBytes.toLocaleString()} bytes
                                        </span>
                                      ) : null}
                                    </li>
                                  ))}
                                  {artifact.variants.length > 3 ? (
                                    <li className="text-[10px] text-neutral-600">
                                      +{artifact.variants.length - 3} more
                                    </li>
                                  ) : null}
                                </ul>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-200">Price components</h2>
        {modelPrices.length === 0 ? (
          <div className="py-6 text-center text-sm text-neutral-500">No price data.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-neutral-500">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Component</th>
                  <th className="px-2 py-1.5 font-medium">Unit</th>
                  <th className="px-2 py-1.5 text-right font-medium">Amount</th>
                  <th className="px-2 py-1.5 text-right font-medium">$/1M tokens</th>
                  <th className="px-2 py-1.5 font-medium">Source</th>
                  <th className="px-2 py-1.5 font-medium">Valid from</th>
                  <th className="px-2 py-1.5 font-medium">Tier</th>
                </tr>
              </thead>
              <tbody>
                {modelPrices.map((r, i) => (
                  <tr key={i} className="border-t border-neutral-800/60">
                    <td className="px-2 py-1.5 text-neutral-200">{r.component}</td>
                    <td className="px-2 py-1.5 text-neutral-400">{r.unit}</td>
                    <td className="px-2 py-1.5 text-right text-neutral-300">{r.amount}</td>
                    <td className="px-2 py-1.5 text-right text-neutral-300">
                      {r.usdPer1m ?? '—'}
                    </td>
                    <td className="px-2 py-1.5 text-neutral-400">{r.sourceId ?? '—'}</td>
                    <td className="px-2 py-1.5 text-neutral-400">{r.validFrom ?? '—'}</td>
                    <td className="px-2 py-1.5 text-neutral-400">
                      {r.tierCondition ? (
                        <span className="rounded bg-sky-950 px-1.5 py-0.5 text-[10px] text-sky-300">
                          {Object.entries(r.tierCondition)
                            .map(([op, v]) => `${op} ${Number(v).toLocaleString()}`)
                            .join(', ')}
                        </span>
                      ) : (
                        'base'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-200">
          Aliases ({modelAliases.length})
        </h2>
        {modelAliases.length === 0 ? (
          <div className="py-6 text-center text-sm text-neutral-500">No aliases.</div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {[...aliasesBySource.entries()].map(([sourceId, list]) => (
              <div key={sourceId}>
                <div className="mb-1 text-xs font-medium text-neutral-500">{sourceId}</div>
                <ul className="space-y-0.5">
                  {list.map((a, i) => (
                    <li key={i} className="text-sm text-neutral-300">
                      <code className="text-xs">{a.alias}</code>{' '}
                      <span className="text-[10px] text-neutral-600">{a.kind}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
