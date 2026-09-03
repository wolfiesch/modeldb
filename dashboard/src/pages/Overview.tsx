import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import LabLogo from '../components/LabLogo'
import { loadElo, loadMeta, loadModels, useData, type Model } from '../lib/data'
import { fmtCount } from '../lib/format'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

const loadTextOverallElo = () => loadElo('text_overall')

const monthFormatter = new Intl.DateTimeFormat('en', { month: 'short', year: 'numeric', timeZone: 'UTC' })

function monthStart(value: number) {
  const date = new Date(value)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)
}

function nextMonthStart(value: number) {
  const date = new Date(value)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)
}

function lastIndexAtOrBefore(values: number[], cutoff: number) {
  let lo = 0
  let hi = values.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2)
    if (values[mid] <= cutoff) {
      found = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

interface FrontierPoint {
  slug: string
  name: string
  dev: string | null
  price: number
  elo: number
  open: number | null
  isFrontier: boolean
}

export default function Overview() {
  const { data: meta, error: metaError } = useData(loadMeta)
  const { data: models, loading, error } = useData(loadModels)
  const { data: eloHistory, loading: eloLoading, error: eloError } = useData(loadTextOverallElo)
  const navigate = useNavigate()
  const [devFilter, setDevFilter] = useState<string | null>(null)
  const [openOnly, setOpenOnly] = useState(false)
  const [showPareto, setShowPareto] = useState(true)
  const [scrubIndex, setScrubIndex] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)

  const months = useMemo(() => {
    if (!eloHistory) return []
    const seen = new Set<number>()
    for (const series of eloHistory.series) {
      for (const t of series.t) seen.add(monthStart(t))
    }
    return [...seen].sort((a, b) => a - b)
  }, [eloHistory])

  useEffect(() => {
    if (months.length === 0) return
    setScrubIndex((current) => {
      if (current == null) return months.length - 1
      return Math.min(current, months.length - 1)
    })
  }, [months])

  useEffect(() => {
    if (!playing || months.length === 0) return
    const timer = window.setInterval(() => {
      setScrubIndex((current) => {
        const next = current == null ? 0 : current + 1
        if (next >= months.length) {
          window.clearInterval(timer)
          setPlaying(false)
          return months.length - 1
        }
        return next
      })
    }, 250)
    return () => window.clearInterval(timer)
  }, [playing, months])

  const selectedMonth =
    scrubIndex == null ? (months.at(-1) ?? null) : (months[Math.min(scrubIndex, months.length - 1)] ?? null)
  const latestMonth = months.at(-1) ?? null
  const isHistorical = selectedMonth != null && latestMonth != null && selectedMonth < latestMonth
  const selectedMonthLabel = selectedMonth == null ? 'Latest' : monthFormatter.format(selectedMonth)

  const eloByModel = useMemo(() => {
    if (!eloHistory || selectedMonth == null) return new Map<number, number>()
    const cutoff = nextMonthStart(selectedMonth) - 1
    const readings = new Map<number, number>()
    for (const series of eloHistory.series) {
      const index = lastIndexAtOrBefore(series.t, cutoff)
      if (index >= 0) readings.set(series.modelId, series.elo[index])
    }
    return readings
  }, [eloHistory, selectedMonth])

  const points = useMemo<FrontierPoint[]>(() => {
    if (!models || selectedMonth == null) return []
    const basePoints = models
      .filter(
        (m): m is Model & { priceOut: number } =>
          m.priceOut != null && m.priceOut > 0 && eloByModel.has(m.id),
      )
      .filter((m) => (devFilter ? m.dev === devFilter : true))
      .filter((m) => (openOnly ? m.open === 1 : true))
      .map((m) => ({
        slug: m.slug,
        name: m.name,
        dev: m.dev,
        price: m.priceOut,
        elo: eloByModel.get(m.id) ?? 0,
        open: m.open,
        isFrontier: false,
      }))

    const ordered = [...basePoints].sort((a, b) => a.price - b.price || b.elo - a.elo)
    let bestElo = -Infinity
    const frontier = new Set<FrontierPoint>()
    for (const point of ordered) {
      if (point.elo > bestElo) {
        frontier.add(point)
        bestElo = point.elo
      }
    }
    return basePoints.map((point) => ({ ...point, isFrontier: frontier.has(point) }))
  }, [models, selectedMonth, eloByModel, devFilter, openOnly])

  const frontierPoints = useMemo(
    () =>
      points
        .filter((point) => point.isFrontier)
        .sort((a, b) => a.price - b.price || a.elo - b.elo),
    [points],
  )

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
      animation: false,
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
        formatter: (p: { data?: { meta?: FrontierPoint } }) => {
          const d = p.data?.meta
          if (!d) return ''
          return `<b>${d.name}</b><br/>$${d.price}/1M out · ELO ${Math.round(d.elo)}${d.open === 1 ? '<br/>open weights' : ''
            }`
        },
      },
      series: [
        ...(showPareto && frontierPoints.length > 1
          ? [
            {
              type: 'line',
              step: 'end',
              symbol: 'none',
              silent: true,
              z: 1,
              lineStyle: { color: '#e0245e', width: 1.5, type: 'dashed' },
              data: frontierPoints.map((point) => [point.price, point.elo]),
            },
          ]
          : []),
        {
          type: 'scatter',
          animation: false,
          z: 2,
          symbolSize: 12,
          data: points.map((p) => ({
            value: [p.price, p.elo],
            meta: p,
            symbol: p.open === 1 ? 'diamond' : 'circle',
            itemStyle: {
              color: colorForDark(p.dev),
              opacity: showPareto ? (p.isFrontier ? 0.95 : 0.35) : 0.85,
              borderColor: showPareto && p.isFrontier ? '#f5f5f5' : 'transparent',
              borderWidth: showPareto && p.isFrontier ? 1 : 0,
            },
          })),
        },
      ],
    }
  }, [points, showPareto, frontierPoints])

  const chartRef = useECharts(option, (params) => {
    const p = params as { data?: { meta?: FrontierPoint } }
    if (p.data?.meta) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  })

  if (loading || eloLoading) return <div className="text-neutral-500">Loading…</div>
  const loadError = error ?? eloError ?? metaError
  if (loadError) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
        <div className="mb-2 text-lg text-neutral-200">Failed to load data</div>
        <div className="mb-4 text-sm text-red-400">{loadError}</div>
        <button
          onClick={() => window.location.reload()}
          className="rounded-full border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:border-neutral-500"
        >
          Retry
        </button>
      </div>
    )
  }
  if (!models || !meta) return null

  const orgs = new Set(models.map((m) => m.dev).filter(Boolean)).size
  const stats = [
    { label: 'Models', value: fmtCount(meta.counts.models) },
    { label: 'Organizations', value: fmtCount(orgs) },
    { label: 'Benchmark results', value: fmtCount(meta.counts.benchmarkResults) },
    { label: 'Price points', value: fmtCount(meta.counts.priceComponents) },
    { label: 'Data as of', value: meta.generatedAt.slice(0, 10) },
  ]

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-5">
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
            onClick={() => setShowPareto((v) => !v)}
            className={`rounded-full border px-3 py-1 text-xs ${showPareto
              ? 'border-pink-500 bg-pink-950 text-pink-300'
              : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
              }`}
          >
            Pareto frontier
          </button>
          <button
            onClick={() => setOpenOnly((v) => !v)}
            className={`rounded-full border px-3 py-1 text-xs ${openOnly
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
              className={`rounded-full border px-3 py-1 text-xs ${devFilter === d
                ? 'border-neutral-300 bg-neutral-800 text-white'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
                }`}
              style={{ borderColor: devFilter === d ? colorForDark(d) : undefined }}
            >
              <LabLogo dev={d} size={16} showLabel labelClassName="truncate" />
            </button>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
          <button
            onClick={() => {
              if (scrubIndex != null && scrubIndex >= months.length - 1) setScrubIndex(0)
              setPlaying((value) => !value)
            }}
            className="rounded-full border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:border-neutral-500"
          >
            {playing ? 'Pause' : 'Play'}
          </button>
          <label className="min-w-28 text-xs text-neutral-400" htmlFor="overview-month-scrub">
            {selectedMonthLabel}
          </label>
          <input
            id="overview-month-scrub"
            type="range"
            min={0}
            max={Math.max(months.length - 1, 0)}
            value={scrubIndex ?? Math.max(months.length - 1, 0)}
            onChange={(event) => {
              setPlaying(false)
              setScrubIndex(Number(event.currentTarget.value))
            }}
            className="min-w-56 flex-1 accent-pink-500"
          />
        </div>
        <p className="mb-2 text-xs text-neutral-500">
          {isHistorical
            ? `LMArena text ELO as of ${selectedMonthLabel} vs current output price. Diamonds = open weights. Click a dot for details.`
            : 'Latest LMArena text ELO vs output price. Diamonds = open weights. Click a dot for details.'}
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
