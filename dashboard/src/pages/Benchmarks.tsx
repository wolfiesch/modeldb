import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { loadBenchmarks, loadModels, useData, type BenchmarkResult } from '../lib/data'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

const DEFAULT_BENCHMARK_ID = 'swe_bench_verified'

export default function Benchmarks() {
  const { data: benchmarks, loading, error } = useData(loadBenchmarks)
  const { data: models } = useData(loadModels)
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
  const modelById = useMemo(() => new Map((models ?? []).map((m) => [m.id, m])), [models])

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
            metric: null,
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
        axisLabel: { color: '#a3a3a3' },
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
          return `<b>${m?.name ?? r.modelId}</b><br/>${r.score}${
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
  }, [latest, models, modelById])

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
        axisLabel: { color: '#a3a3a3' },
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
          return `<b>${d.name}</b><br/>score ${d.score} · $${d.costPerPoint.toFixed(
            4,
          )}/point${d.selfReported === 1 ? ' · self-reported' : ''}`
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
  }, [latest, models, modelById])

  const barRef = useECharts(barOption)
  const scatterRef = useECharts(scatterOption, (params) => {
    const p = params as { data?: { meta?: { slug?: string } } }
    if (p.data?.meta?.slug) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  })

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!benchmarks) return null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-lg font-semibold text-neutral-100">Benchmarks</h1>
        {benchmarks.map((b) => (
          <button
            key={b.id}
            onClick={() => setBenchId(b.id)}
            className={`rounded-full border px-3 py-1 text-xs ${
              benchId === b.id
                ? 'border-neutral-300 bg-neutral-800 text-white'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            {b.name}
          </button>
        ))}
      </div>
      {bench && (
        <div className="text-xs text-neutral-500">
          {bench.category ?? 'uncategorized'} · metric: {bench.metricDefault ?? '—'} ·{' '}
          {latest.length} models{' '}
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
      )}
      <div className="grid gap-6 xl:grid-cols-2">
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <h2 className="mb-1 text-sm font-semibold text-neutral-200">
            Leaderboard (latest score, top 40)
          </h2>
          <p className="mb-2 text-xs text-neutral-500">
            Faded / amber-outlined bars are self-reported scores.
          </p>
          {barOption ? (
            <div ref={barRef} className="h-[640px] w-full" />
          ) : (
            <div className="py-16 text-center text-sm text-neutral-500">No results.</div>
          )}
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
