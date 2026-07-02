import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { loadMeta, loadModels, useData, type Model } from '../lib/data'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

interface FrontierPoint {
  slug: string
  name: string
  dev: string | null
  price: number
  elo: number
  open: number | null
}

export default function Overview() {
  const { data: meta } = useData(loadMeta)
  const { data: models, loading, error } = useData(loadModels)
  const navigate = useNavigate()
  const [devFilter, setDevFilter] = useState<string | null>(null)
  const [openOnly, setOpenOnly] = useState(false)

  const points = useMemo(() => {
    if (!models) return []
    return models
      .filter(
        (m): m is Model & { priceOut: number } =>
          m.priceOut != null && m.scores.lmarena_text_overall != null,
      )
      .filter((m) => (devFilter ? m.dev === devFilter : true))
      .filter((m) => (openOnly ? m.open === 1 : true))
      .map((m) => ({
        slug: m.slug,
        name: m.name,
        dev: m.dev,
        price: m.priceOut,
        elo: m.scores.lmarena_text_overall.score,
        open: m.open,
      }))
  }, [models, devFilter, openOnly])

  const devs = useMemo(() => {
    if (!models) return []
    const seen = new Set<string>()
    for (const m of models) {
      if (m.dev && m.priceOut != null && m.scores.lmarena_text_overall != null) seen.add(m.dev)
    }
    return [...seen].sort()
  }, [models])

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (points.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 60, right: 24, top: 24, bottom: 48 },
      xAxis: {
        type: 'log',
        name: 'Output $/1M tokens (log)',
        nameLocation: 'middle',
        nameGap: 32,
        axisLabel: { color: '#a3a3a3' },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      yAxis: {
        type: 'value',
        name: 'LMArena ELO',
        scale: true,
        axisLabel: { color: '#a3a3a3' },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: FrontierPoint } }) => {
          const d = p.data.meta
          return `<b>${d.name}</b><br/>$${d.price}/1M out · ELO ${Math.round(d.elo)}${
            d.open === 1 ? '<br/>open weights' : ''
          }`
        },
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 12,
          data: points.map((p) => ({
            value: [p.price, p.elo],
            meta: p,
            symbol: p.open === 1 ? 'diamond' : 'circle',
            itemStyle: { color: colorForDark(p.dev), opacity: 0.85 },
          })),
        },
      ],
    }
  }, [points])

  const chartRef = useECharts(option, (params) => {
    const p = params as { data?: { meta?: FrontierPoint } }
    if (p.data?.meta) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  })

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!models || !meta) return null

  const orgs = new Set(models.map((m) => m.dev).filter(Boolean)).size

  const stats = [
    { label: 'Models', value: meta.counts.models.toLocaleString() },
    { label: 'Organizations', value: String(orgs) },
    { label: 'Benchmark results', value: meta.counts.benchmarkResults.toLocaleString() },
    { label: 'Price points', value: meta.counts.priceComponents.toLocaleString() },
    { label: 'Data as of', value: meta.generatedAt.slice(0, 10) },
  ]

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {stats.map((s) => (
          <div key={s.label} className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <div className="text-xl font-semibold text-neutral-100">{s.value}</div>
            <div className="text-xs text-neutral-500">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="mr-4 text-base font-semibold text-neutral-100">
            Price vs ELO frontier
          </h2>
          <button
            onClick={() => setOpenOnly((v) => !v)}
            className={`rounded-full border px-3 py-1 text-xs ${
              openOnly
                ? 'border-emerald-500 bg-emerald-950 text-emerald-300'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            open weights
          </button>
          {devs.map((d) => (
            <button
              key={d}
              onClick={() => setDevFilter((cur) => (cur === d ? null : d))}
              className={`rounded-full border px-3 py-1 text-xs ${
                devFilter === d
                  ? 'border-neutral-300 bg-neutral-800 text-white'
                  : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
              }`}
              style={{ borderColor: devFilter === d ? colorForDark(d) : undefined }}
            >
              {d}
            </button>
          ))}
        </div>
        <p className="mb-2 text-xs text-neutral-500">
          Latest LMArena text ELO vs output price. Diamonds = open weights. Click a dot for
          details.
        </p>
        {points.length === 0 ? (
          <div className="py-16 text-center text-neutral-500">No models match.</div>
        ) : (
          <div ref={chartRef} className="h-[480px] w-full" />
        )}
      </div>
    </div>
  )
}
