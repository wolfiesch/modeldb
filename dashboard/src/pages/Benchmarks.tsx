import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import ChartState, { resolveChartStatus } from '../components/ChartState'
import { EvidenceInspector } from '../components/EvidenceInspector'
import { loadBenchmarks, loadModels, useData } from '../lib/data'
import type { BenchmarkResult } from '../lib/data'
import { fmtBenchmarkScore, fmtCount } from '../lib/format'
import { labLabel } from '../lib/labs'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

const DEFAULT_BENCHMARK_ID = 'swe_bench_verified'

const FEATURED_BENCHMARK_PRIORITY: Record<string, number> = {
  deepswe: 0,
  swe_bench_verified: 1,
  lmarena_text_coding: 2,
  aider_polyglot: 3,
}

const FEATURED_BENCHMARK_FALLBACK_PRIORITY = Object.keys(FEATURED_BENCHMARK_PRIORITY).length

export default function Benchmarks() {
  const { data: benchmarks, loading, error } = useData(loadBenchmarks)
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [benchId, setBenchId] = useState(() => params.get('b') ?? DEFAULT_BENCHMARK_ID)

  useEffect(() => {
    if (!benchmarks || benchmarks.some((b) => b.id === benchId)) return
    setBenchId(DEFAULT_BENCHMARK_ID)
  }, [benchmarks, benchId])

  useEffect(() => {
    const next = new URLSearchParams()
    if (benchId !== DEFAULT_BENCHMARK_ID) next.set('b', benchId)
    setParams(next, { replace: true })
  }, [benchId, setParams])

  const bench = benchmarks?.find((b) => b.id === benchId) ?? null
  const displayBenchmarks = useMemo(() => {
    if (!benchmarks) return []
    return [...benchmarks].sort((a, b) => {
      const aPriority = FEATURED_BENCHMARK_PRIORITY[a.id] ?? FEATURED_BENCHMARK_FALLBACK_PRIORITY
      const bPriority = FEATURED_BENCHMARK_PRIORITY[b.id] ?? FEATURED_BENCHMARK_FALLBACK_PRIORITY
      return aPriority - bPriority || a.name.localeCompare(b.name)
    })
  }, [benchmarks])
  const modelById = useMemo(() => new Map((models ?? []).map((m) => [m.id, m])), [models])
  const formatBenchmarkScore = useMemo(
    () => (value: number | null | undefined) => fmtBenchmarkScore(value, bench?.metricDefault),
    [bench?.metricDefault],
  )

  // Latest result per model (results are ordered by measured_at asc).
  const latest = useMemo(() => {
    const map = new Map<number, BenchmarkResult>()
    if (bench?.results) {
      for (const r of bench.results) map.set(r.modelId, r)
    } else if (bench && models) {
      // LMArena benchmarks: use the pre-baked latest scores on models.json.
      for (const m of models) {
        const s = m.scores[bench.id]
        if (s) {
          map.set(m.id, {
            modelId: m.id,
            score: s.score,
            metric: s.metric,
            rank: s.rank,
            selfReported: s.selfReported,
            measuredAt: s.measuredAt,
          })
        }
      }
    }
    return [...map.values()].sort((a, b) => b.score - a.score)
  }, [bench, models])

  const barOption = useMemo<EChartsCoreOption | null>(() => {
    if (latest.length === 0 || !models) return null
    const rows = latest.slice(0, 40).reverse()
    return {
      backgroundColor: 'transparent',
      grid: { left: 150, right: 48, top: 8, bottom: 32 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#a3a3a3', formatter: (value: number) => formatBenchmarkScore(value) },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      yAxis: {
        type: 'category',
        data: rows.map((r) => modelById.get(r.modelId)?.name ?? String(r.modelId)),
        axisLabel: { color: '#d4d4d4', fontSize: 11 },
      },
      tooltip: {
        trigger: 'item',
        formatter: (p: { dataIndex: number }) => {
          const r = rows[p.dataIndex]
          const m = modelById.get(r.modelId)
          return `<b>${m?.name ?? r.modelId}</b><br/>${labLabel(m?.dev)}<br/>${formatBenchmarkScore(r.score)}${
            r.selfReported === 1 ? ' · self-reported' : ''
          }`
        },
      },
      series: [
        {
          type: 'bar',
          data: rows.map((r) => ({
            value: r.score,
            meta: r,
            itemStyle: {
              color: colorForDark(modelById.get(r.modelId)?.dev),
              opacity: r.selfReported === 1 ? 0.45 : 0.9,
              borderColor: r.selfReported === 1 ? '#fbbf24' : undefined,
              borderWidth: r.selfReported === 1 ? 1 : 0,
            },
          })),
          barMaxWidth: 14,
        },
      ],
    }
  }, [latest, models, modelById, formatBenchmarkScore])

  const scatterOption = useMemo<EChartsCoreOption | null>(() => {
    if (latest.length === 0 || !models) return null
    const pts = latest
      .map((r) => {
        const m = modelById.get(r.modelId)
        if (!m || m.priceOut == null || r.score <= 0) return null
        return {
          name: m.name,
          slug: m.slug,
          dev: m.dev,
          score: r.score,
          costPerPoint: m.priceOut / r.score,
          selfReported: r.selfReported,
        }
      })
      .filter((p) => p != null)
    if (pts.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 64, right: 24, top: 24, bottom: 48 },
      xAxis: {
        type: 'value',
        name: 'Score',
        scale: true,
        nameLocation: 'middle',
        nameGap: 30,
        axisLabel: { color: '#a3a3a3', formatter: (value: number) => formatBenchmarkScore(value) },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      yAxis: {
        type: 'log',
        name: '$ out/1M per point (log)',
        axisLabel: { color: '#a3a3a3' },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: (typeof pts)[number] } }) => {
          const d = p.data.meta
          return `<b>${d.name}</b><br/>${labLabel(d.dev)}<br/>score ${formatBenchmarkScore(
            d.score,
          )} · $${d.costPerPoint.toFixed(4)}/point${d.selfReported === 1 ? ' · self-reported' : ''}`
        },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 11,
          data: pts.map((p) => ({
            value: [p.score, p.costPerPoint],
            meta: p,
            itemStyle: { color: colorForDark(p.dev), opacity: 0.85 },
          })),
        },
      ],
    }
  }, [latest, models, modelById, formatBenchmarkScore])

  const barRef = useECharts(barOption)
  const scatterRef = useECharts(scatterOption, (params) => {
    const p = params as { data?: { meta?: { slug?: string } } }
    if (p.data?.meta?.slug) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  })
  const barRowCount = Math.min(latest.length, 40)
  const hasBarData = barOption != null && barRowCount > 0
  const chartError = error ?? modelsError
  const chartStatus = resolveChartStatus({
    loading: loading || modelsLoading,
    error: chartError,
    hasData: hasBarData,
    rowCount: hasBarData ? barRowCount : 0,
  })
  const scoredModelCount = latest.length
  const hasSelfReported = latest.some((r) => r.selfReported === 1)
  const directionLabel = bench?.higherIsBetter === 0 ? 'Lower is better' : 'Higher is better'
  const provenanceNote = `${directionLabel}.${hasSelfReported ? ' Faded / amber-outlined marks are self-reported.' : ''}`

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-lg font-semibold text-neutral-100">Benchmarks</h1>
        {displayBenchmarks.map((b) => (
          <button
            key={b.id}
            onClick={() => setBenchId(b.id)}
            className={`flex items-center gap-2 rounded-full border px-3 py-1 text-xs ${
              benchId === b.id
                ? b.id === 'deepswe'
                  ? 'border-cyan-300 bg-cyan-950 text-cyan-50'
                  : 'border-neutral-300 bg-neutral-800 text-white'
                : b.id === 'deepswe'
                  ? 'border-cyan-800 text-cyan-300 hover:border-cyan-500'
                  : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            <span>{b.name}</span>
            {b.id === 'deepswe' ? (
              <span className="rounded-full bg-cyan-950 px-2 py-0.5 text-[10px] uppercase tracking-wide text-cyan-300">
                Long-horizon coding
              </span>
            ) : null}
          </button>
        ))}
      </div>
      {bench && (
        <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
          <div className="text-xs text-neutral-500">
            {bench.id === 'deepswe' ? 'long-horizon coding' : (bench.category ?? 'uncategorized')} · metric:{' '}
            {bench.metricDefault ?? '-'} · {fmtCount(scoredModelCount)} models{' '}
            {bench.sourceUrl && (
              <a
                href={bench.sourceUrl}
                target="_blank"
                rel="noreferrer"
                className="text-blue-400 hover:underline"
              >
                source
              </a>
            )}
          </div>
          <div className="rounded border border-neutral-800 bg-neutral-900 p-3 text-xs text-neutral-400">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-neutral-500">
              Benchmark metadata
            </div>
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1">
              <dt className="text-neutral-500">Label</dt>
              <dd className="truncate text-neutral-200">{bench.name}</dd>
              <dt className="text-neutral-500">Category</dt>
              <dd className="text-neutral-300">
                {bench.id === 'deepswe' ? 'long-horizon coding' : (bench.category ?? 'uncategorized')}
              </dd>
              <dt className="text-neutral-500">Models scored</dt>
              <dd className="text-neutral-300">{fmtCount(scoredModelCount)}</dd>
              <dt className="text-neutral-500">Direction</dt>
              <dd className="text-neutral-300">{directionLabel}</dd>
            </dl>
          </div>
        </div>
      )}
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-1 text-sm font-semibold text-neutral-200">
            Leaderboard (latest score, top 40)
          </h2>
          <p className="mb-2 text-xs text-neutral-500">
            Faded / amber-outlined bars are self-reported scores.
          </p>
          <ChartState
            status={chartStatus}
            minHeight={640}
            errorLabel={chartError ?? 'Unable to load benchmark results.'}
            emptyLabel="No models have scored results for the selected benchmark."
            footer={{
              source: bench?.name,
              shown: barRowCount,
              total: scoredModelCount,
              note: provenanceNote,
            }}
          >
            <div ref={barRef} className="h-[640px] w-full" />
          </ChartState>
          <div className="mt-4 border-t border-neutral-800 pt-3">
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-neutral-400">Score evidence</h3>
            <div className="max-h-56 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-neutral-900 text-left text-neutral-500">
                  <tr>
                    <th className="py-1 font-medium">Model</th>
                    <th className="py-1 text-right font-medium">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {latest.slice(0, 40).map((result) => {
                    const model = modelById.get(result.modelId)
                    return (
                      <tr key={result.modelId} className="border-t border-neutral-800/60">
                        <td className="py-1.5 text-neutral-300">{model?.name ?? result.modelId}</td>
                        <td className="py-1.5 text-right">
                          {bench ? (
                            <EvidenceInspector
                              benchmark={bench}
                              result={result}
                              label={formatBenchmarkScore(result.score)}
                            />
                          ) : null}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-1 text-sm font-semibold text-neutral-200">Cost per point</h2>
          <p className="mb-2 text-xs text-neutral-500">
            Output-token dollars per benchmark point. Click a dot for model detail.
          </p>
          {scatterOption ? (
            <div ref={scatterRef} className="h-[640px] w-full" />
          ) : (
            <div className="py-16 text-center text-sm text-neutral-500">
              No models with both a score and a price.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
