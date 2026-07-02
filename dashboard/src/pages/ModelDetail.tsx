import { useMemo } from 'react'
import { Link, useParams } from 'react-router'
import {
  loadAliases,
  loadBenchmarks,
  loadEnrichment,
  loadElo,
  loadModels,
  loadPrices,
  loadRunOptions,
  useData,
} from '../lib/data'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'
import type { RunOptionPrice, RunOptionVariant } from '../lib/data'

const loadOverall = () => loadElo('text_overall')
const loadCoding = () => loadElo('text_coding')

const artificialAnalysisLabels = [
  ['artificial_analysis_intelligence_index', 'Intelligence'],
  ['artificial_analysis_coding_index', 'Coding'],
  ['artificial_analysis_math_index', 'Math'],
] as const

function formatTokenBudget(value: number | null) {
  return value == null ? 'n/a' : value.toLocaleString()
}

function formatRunPrice(price: RunOptionPrice | undefined) {
  if (!price) return 'n/a'
  if (price.usdPer1m != null) return `$${price.usdPer1m}`
  return `${price.amount} / ${price.unit}`
}

function priceFor(prices: RunOptionPrice[], component: string) {
  return prices.find((price) => price.component === component)
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

export default function ModelDetail() {
  const { slug = '' } = useParams()
  const { data: models, loading } = useData(loadModels)
  const { data: benchmarks } = useData(loadBenchmarks)
  const { data: prices } = useData(loadPrices)
  const { data: aliases } = useData(loadAliases)
  const { data: eloOverall } = useData(loadOverall)
  const { data: eloCoding } = useData(loadCoding)
  const { data: runOptions } = useData(loadRunOptions)
  const { data: enrichment } = useData(loadEnrichment)

  const model = useMemo(
    () => models?.find((m) => m.slug === decodeURIComponent(slug)) ?? null,
    [models, slug],
  )

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
  const aliasesBySource = new Map<string, typeof modelAliases>()
  for (const a of modelAliases) {
    const list = aliasesBySource.get(a.sourceId) ?? []
    list.push(a)
    aliasesBySource.set(a.sourceId, list)
  }

  const benchName = new Map((benchmarks ?? []).map((b) => [b.id, b.name]))
  const scoreEntries = Object.entries(model.scores).sort(
    (a, b) => (b[1].score ?? 0) - (a[1].score ?? 0),
  )
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
    vllmRows.length > 0

  const specs: Array<[string, string]> = [
    ['Slug', model.slug],
    ['Developer', model.devName ?? model.dev ?? '—'],
    ['Family', model.family ?? '—'],
    ['Generation', model.generation ?? '—'],
    ['Tier / variant', model.tier ?? '—'],
    ['Parameters', model.params ?? '—'],
    ['Training role', model.role ?? '—'],
    ['Released', model.released ?? '—'],
    ['Knowledge cutoff', model.cutoff ?? '—'],
    ['Stability', model.stability ?? '—'],
    ['Open weights', model.open === 1 ? 'yes' : model.open === 0 ? 'no' : '—'],
    ['Context window', model.ctx == null ? '—' : model.ctx.toLocaleString()],
    ['Max output', model.maxOut == null ? '—' : model.maxOut.toLocaleString()],
    ['Input modalities', model.inMod?.join(', ') ?? '—'],
    ['Output modalities', model.outMod?.join(', ') ?? '—'],
    ['$ in / 1M', model.priceIn == null ? '—' : `$${model.priceIn}`],
    ['$ out / 1M', model.priceOut == null ? '—' : `$${model.priceOut}`],
    ['$ cache read / 1M', model.priceCacheRead == null ? '—' : `$${model.priceCacheRead}`],
    ['$ cache write / 1M', model.priceCacheWrite == null ? '—' : `$${model.priceCacheWrite}`],
  ]

  return (
    <div className="space-y-6">
      <div>
        <Link to="/models" className="text-xs text-neutral-500 hover:text-neutral-300">
          ← Model Explorer
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="flex items-center gap-3 text-2xl font-bold text-neutral-100">
            <span
              className="inline-block h-3 w-3 rounded-full"
              style={{ backgroundColor: colorForDark(model.dev) }}
            />
            {model.name}
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
                      {v}
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
                  {scoreEntries.map(([id, s]) => (
                    <tr key={id} className="border-t border-neutral-800/60 first:border-t-0">
                      <td className="py-1.5 text-neutral-300">{benchName.get(id) ?? id}</td>
                      <td className="py-1.5 text-right text-neutral-100">
                        {id.startsWith('lmarena_')
                          ? Math.round(s.score)
                          : Number(s.score.toFixed(s.score < 1 ? 3 : 1))}
                      </td>
                      <td className="w-24 py-1.5 pl-3 text-right">
                        {s.selfReported === 1 && (
                          <span className="rounded bg-amber-950 px-1.5 py-0.5 text-[10px] text-amber-400">
                            self-reported
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
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
                                {Number(signal.score.toFixed(signal.score < 1 ? 3 : 1))}
                              </td>
                            </tr>
                          ) : null,
                        )}
                      </tbody>
                    </table>
                  </div>
                ) : null}

                {modelEnrichment?.medianOutputTokensPerSecond ||
                modelEnrichment?.medianTimeToFirstTokenSeconds ? (
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
                  <table className="w-full text-sm">
                    <thead className="text-left text-xs text-neutral-500">
                      <tr>
                        <th className="px-2 py-1.5 font-medium">Provider</th>
                        <th className="px-2 py-1.5 font-medium">Surface</th>
                        <th className="px-2 py-1.5 font-medium">Endpoint model id</th>
                        <th className="px-2 py-1.5 text-right font-medium">Context</th>
                        <th className="px-2 py-1.5 text-right font-medium">Max output</th>
                        <th className="px-2 py-1.5 text-right font-medium">Input $/1M</th>
                        <th className="px-2 py-1.5 text-right font-medium">Output $/1M</th>
                      </tr>
                    </thead>
                    <tbody>
                      {modelRunOptions.surfaces.map((surface, i) => (
                        <tr key={`${surface.providerId}:${surface.endpointModelId}:${i}`} className="border-t border-neutral-800/60">
                          <td className="px-2 py-1.5 text-neutral-200">{surface.providerId}</td>
                          <td className="px-2 py-1.5 text-neutral-400">
                            {surface.surfaceType ?? 'n/a'}
                            {surface.region ? (
                              <span className="ml-1 text-[10px] text-neutral-600">{surface.region}</span>
                            ) : null}
                          </td>
                          <td className="px-2 py-1.5 text-neutral-300">
                            <code className="text-xs">{surface.endpointModelId}</code>
                          </td>
                          <td className="px-2 py-1.5 text-right text-neutral-300">
                            {formatTokenBudget(surface.contextWindow)}
                          </td>
                          <td className="px-2 py-1.5 text-right text-neutral-300">
                            {formatTokenBudget(surface.maxOutput)}
                          </td>
                          <td className="px-2 py-1.5 text-right text-neutral-300">
                            {formatRunPrice(priceFor(surface.prices, 'input_token'))}
                          </td>
                          <td className="px-2 py-1.5 text-right text-neutral-300">
                            {formatRunPrice(priceFor(surface.prices, 'output_token'))}
                          </td>
                        </tr>
                      ))}
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
