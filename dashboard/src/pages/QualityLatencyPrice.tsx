import { useMemo, useState } from 'react'
import { loadEnrichment, loadModels, useData } from '../lib/data'
import DevFilter from '../components/DevFilter'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import ChartState, { resolveChartStatus } from '../components/ChartState'
import { fmtElo, fmtPercent, fmtPrice, fmtSeconds, fmtTps } from '../lib/format'
import type { EChartsCoreOption } from 'echarts/core'

interface ScatterPoint {
  modelId: number
  name: string
  slug: string
  dev: string | null
  speed: number | null      // tokens/sec
  latency: number | null    // TTFT seconds
  quality: number           // score
  price: number | null      // output price $/1M
  open: boolean
  isFrontier: boolean
}

type XMetric = 'speed' | 'latency'
type YMetric = 'intelligence' | 'coding' | 'math' | 'elo'

const Y_METRIC_LABELS: Record<YMetric, string> = {
  intelligence: 'AA Intelligence Index',
  coding: 'AA Coding Index',
  math: 'AA Math Index',
  elo: 'LMArena ELO',
}

const Y_METRIC_BENCHMARKS: Record<YMetric, string> = {
  intelligence: 'artificial_analysis_intelligence_index',
  coding: 'artificial_analysis_coding_index',
  math: 'artificial_analysis_math_index',
  elo: 'lmarena_text_overall',
}

export default function QualityLatencyPrice() {
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const { data: enrichment, loading: enrichLoading, error: enrichError } = useData(loadEnrichment)

  const [xMetric, setXMetric] = useState<XMetric>('speed')
  const [yMetric, setYMetric] = useState<YMetric>('intelligence')
  const [openOnly, setOpenOnly] = useState<boolean>(false)
  const [devFilter, setDevFilter] = useState<string | null>(null)
  const [showPareto, setShowPareto] = useState<boolean>(true)
  const [maxPrice, setMaxPrice] = useState<number>(100)

  const points = useMemo<ScatterPoint[]>(() => {
    if (!models || !enrichment) return []

    const basePoints: ScatterPoint[] = models
      .map((m) => {
        const e = enrichment[String(m.id)]
        if (!e) return null

        // 1. Get speed and latency
        const speedVal = e.medianOutputTokensPerSecond?.value
        const speed = typeof speedVal === 'number' ? speedVal : null
        const latencyVal = e.medianTimeToFirstTokenSeconds?.value
        const latency = typeof latencyVal === 'number' ? latencyVal : null

        // 2. Get quality score based on selected metric
        let quality: number | null = null
        if (yMetric === 'elo') {
          quality = m.scores.lmarena_text_overall?.score ?? null
        } else {
          const benchId = Y_METRIC_BENCHMARKS[yMetric]
          quality = e.artificialAnalysis?.[benchId]?.score ?? null
        }

        if (quality == null) return null
        if (xMetric === 'speed' && (speed == null || speed <= 0)) return null
        if (xMetric === 'latency' && (latency == null || latency <= 0)) return null

        return {
          modelId: m.id,
          name: m.name,
          slug: m.slug,
          dev: m.dev,
          speed: speed ?? null,
          latency: latency ?? null,
          quality,
          price: m.priceOut,
          open: m.open === 1,
          isFrontier: false,
        }
      })
      .filter((p): p is ScatterPoint => p !== null)
      .filter((p) => (p.price === null || p.price <= maxPrice))
      .filter((p) => (openOnly ? p.open : true))
      .filter((p) => (devFilter ? p.dev === devFilter : true))

    if (basePoints.length === 0) return []

    // Compute Pareto frontier.
    // If xMetric is speed (higher is better) and quality is higher is better:
    // Sort by X descending. Walk and keep points that have higher Y than any seen so far.
    // If xMetric is latency (lower is better):
    // Sort by X ascending. Walk and keep points that have higher Y than any seen so far.
    const sorted = [...basePoints].sort((a, b) => {
      const valA = xMetric === 'speed' ? (a.speed ?? 0) : (a.latency ?? 999)
      const valB = xMetric === 'speed' ? (b.speed ?? 0) : (b.latency ?? 999)
      return xMetric === 'speed' ? valB - valA : valA - valB
    })

    let maxQuality = -Infinity
    const frontierSet = new Set<number>()

    for (const p of sorted) {
      if (p.quality > maxQuality) {
        frontierSet.add(p.modelId)
        maxQuality = p.quality
      }
    }

    return basePoints.map((p) => ({
      ...p,
      isFrontier: frontierSet.has(p.modelId),
    }))
  }, [models, enrichment, xMetric, yMetric, openOnly, devFilter, maxPrice])

  const frontierPoints = useMemo(() => {
    return points
      .filter((p) => p.isFrontier)
      .sort((a, b) => {
        const valA = xMetric === 'speed' ? (a.speed ?? 0) : (a.latency ?? 0)
        const valB = xMetric === 'speed' ? (b.speed ?? 0) : (b.latency ?? 0)
        return valA - valB
      })
  }, [points, xMetric])

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (points.length === 0) return null

    const seriesData = points.map((p) => {
      const xVal = xMetric === 'speed' ? p.speed : p.latency
      let size = 12
      if (p.price !== null) {
        if (p.price === 0) {
          size = 24
        } else {
          size = Math.max(6, Math.min(22, 20 - Math.log(p.price) * 3))
        }
      }
      return {
        value: [xVal, p.quality],
        meta: p,
        symbol: p.open ? 'diamond' : 'circle',
        symbolSize: size,
        itemStyle: {
          color: colorForDark(p.dev),
          opacity: showPareto ? (p.isFrontier ? 0.95 : 0.35) : 0.85,
          borderColor: showPareto && p.isFrontier ? '#f5f5f5' : 'transparent',
          borderWidth: showPareto && p.isFrontier ? 1.5 : 0,
        },
        label: p.isFrontier
          ? { show: true, position: 'top', formatter: p.name, color: '#e5e5e5', fontSize: 10 }
          : undefined,
      }
    })

    const lineData = frontierPoints.map((p) => {
      const xVal = xMetric === 'speed' ? p.speed : p.latency
      return [xVal, p.quality]
    })

    return {
      backgroundColor: 'transparent',
      grid: { left: 60, right: 32, top: 32, bottom: 48 },
      xAxis: {
        type: 'value',
        name: xMetric === 'speed' ? 'Speed (Tokens/sec)' : 'Latency (TTFT seconds)',
        nameLocation: 'middle',
        nameGap: 32,
        scale: true,
        axisLabel: { color: '#a3a3a3', formatter: (value: number) => xMetric === 'speed' ? fmtTps(value).replace(' tok/s', '') : fmtSeconds(value) },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      yAxis: {
        type: 'value',
        name: Y_METRIC_LABELS[yMetric],
        scale: true,
        axisLabel: { color: '#a3a3a3', formatter: (value: number) => yMetric === 'elo' ? fmtElo(value) : fmtPercent(value) },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      tooltip: {
        trigger: 'item',
        formatter: (params: { data?: { meta?: ScatterPoint } }) => {
          const d = params.data?.meta
          if (!d) return ''
          return `<b>${d.name}</b><br/>` +
            `Quality: ${yMetric === 'elo' ? fmtElo(d.quality) : fmtPercent(d.quality)}<br/>` +
            `Speed: ${fmtTps(d.speed)}<br/>` +
            `Latency: ${fmtSeconds(d.latency)} TTFT<br/>` +
            `Price: ${d.price != null ? `${fmtPrice(d.price)}/1M out` : 'Unknown'}`
        },
      },
      series: [
        ...(showPareto && lineData.length > 1
          ? [
              {
                type: 'line',
                symbol: 'none',
                silent: true,
                z: 1,
                lineStyle: { color: '#10b981', width: 2, type: 'dashed' },
                data: lineData,
              },
            ]
          : []),
        {
          type: 'scatter',
          z: 2,
          symbolSize: (_val: unknown, params: { data?: { symbolSize?: number } }) => params.data?.symbolSize ?? 12,
          data: seriesData,
        },
      ],
    }
  }, [points, frontierPoints, xMetric, yMetric, showPareto])

  const chartRef = useECharts(option)

  const devs = useMemo(() => {
    if (!models) return []
    const seen = new Set<string>()
    for (const m of models) {
      if (m.dev) seen.add(m.dev)
    }
    return [...seen].sort()
  }, [models])

  const status = resolveChartStatus({
    loading: modelsLoading || enrichLoading,
    error: modelsError ?? enrichError,
    hasData: !!models && !!enrichment,
    rowCount: points.length,
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-neutral-100">Quality vs Latency / Speed Frontier</h1>
        <p className="mt-1 text-xs text-neutral-500">
          Visualize AI models along the operational frontier of capability, inference throughput, and response latency based on Artificial Analysis measurements.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-neutral-500" htmlFor="x-axis-metric">X Axis (Performance)</label>
          <div className="flex rounded border border-neutral-700 bg-neutral-950 p-0.5">
            <button
              onClick={() => setXMetric('speed')}
              className={`rounded px-2.5 py-1 text-xs ${
                xMetric === 'speed' ? 'bg-neutral-800 text-white font-medium' : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              Speed (tok/s)
            </button>
            <button
              onClick={() => setXMetric('latency')}
              className={`rounded px-2.5 py-1 text-xs ${
                xMetric === 'latency' ? 'bg-neutral-800 text-white font-medium' : 'text-neutral-400 hover:text-neutral-200'
              }`}
            >
              Latency (TTFT)
            </button>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-neutral-500" htmlFor="y-axis-metric">Y Axis (Quality)</label>
          <select
            id="y-axis-metric"
            value={yMetric}
            onChange={(e) => {
              const val = e.target.value
              if (val === 'intelligence' || val === 'coding' || val === 'math' || val === 'elo') {
                setYMetric(val)
              }
            }}
            className="rounded border border-neutral-700 bg-neutral-950 px-2.5 py-1.5 text-xs text-neutral-200"
          >
            {Object.entries(Y_METRIC_LABELS).map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-neutral-500">Pareto Frontier</span>
          <button
            onClick={() => setShowPareto((v) => !v)}
            className={`rounded border px-3 py-1 text-xs ${
              showPareto
                ? 'border-pink-500 bg-pink-950 text-pink-300'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            Efficient Frontier
          </button>
        </div>

        <div className="flex flex-col gap-1 min-w-40">
          <label className="text-[10px] uppercase tracking-wider text-neutral-500" htmlFor="max-price-filter">
            Max Price: {maxPrice === 100 ? 'Any' : `${fmtPrice(maxPrice)}/1M`}
          </label>
          <input
            id="max-price-filter"
            type="range"
            min={0}
            max={100}
            value={maxPrice}
            onChange={(e) => setMaxPrice(Number(e.target.value))}
            className="accent-pink-500"
          />
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-neutral-500">Weights</span>
          <button
            onClick={() => setOpenOnly((prev) => !prev)}
            className={`rounded border px-3 py-1 text-xs ${
              openOnly
                ? 'border-emerald-500 bg-emerald-950 text-emerald-300'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            open weights only
          </button>
        </div>

        <div className="flex flex-col gap-1">
          <span className="text-[10px] uppercase tracking-wider text-neutral-500">Developer</span>
          <DevFilter devs={devs} value={devFilter} onChange={setDevFilter} />
        </div>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <ChartState
          status={status}
          minHeight={480}
          emptyLabel="No models match filters or have measurements."
          footer={{
            source: 'Artificial Analysis + LMArena',
            shown: points.length,
            total: models?.length ?? undefined,
            note: showPareto ? 'Highlighted points are on the efficient (Pareto) frontier.' : undefined,
          }}
        >
          <div ref={chartRef} className="h-[480px] w-full" />
        </ChartState>
      </div>
    </div>
  )
}
