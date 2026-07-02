import { useMemo } from 'react'
import { useNavigate } from 'react-router'
import { loadBenchmarks, loadModels, useData } from '../lib/data'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

interface Point {
  slug: string
  name: string
  dev: string | null
}

const darkAxis = {
  axisLabel: { color: '#a3a3a3' },
  nameTextStyle: { color: '#737373' },
  splitLine: { lineStyle: { color: '#262626' } },
}

export default function Landscape() {
  const { data: models, loading, error } = useData(loadModels)
  const { data: benchmarks } = useData(loadBenchmarks)
  const navigate = useNavigate()

  const goTo = (params: unknown) => {
    const p = params as { data?: { meta?: Point } }
    if (p.data?.meta?.slug) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  }

  // 1. Context-window arms race
  const ctxOption = useMemo<EChartsCoreOption | null>(() => {
    if (!models) return null
    const pts = models.filter((m) => m.released && m.ctx != null && m.ctx > 0)
    if (pts.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 72, right: 24, top: 24, bottom: 48 },
      xAxis: { type: 'time', name: 'Release date', nameLocation: 'middle', nameGap: 32, ...darkAxis, splitLine: { show: false } },
      yAxis: { type: 'log', name: 'Context window (tokens, log)', ...darkAxis },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: Point; value: [string, number] } }) =>
          `<b>${p.data.meta.name}</b><br/>${p.data.value[0]} · ${p.data.value[1].toLocaleString()} tokens`,
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 9,
          data: pts.map((m) => ({
            value: [m.released, m.ctx],
            meta: { slug: m.slug, name: m.name, dev: m.dev },
            itemStyle: { color: colorForDark(m.dev), opacity: 0.8 },
          })),
        },
      ],
    }
  }, [models])

  // 2. Knowledge freshness (cutoff vs release)
  const freshOption = useMemo<EChartsCoreOption | null>(() => {
    if (!models) return null
    const pts = models.filter(
      (m) => m.released && m.cutoff && /^\d{4}-\d{2}/.test(m.cutoff),
    )
    if (pts.length === 0) return null
    const dates = pts.flatMap((m) => [Date.parse(m.released!), Date.parse(m.cutoff! + (m.cutoff!.length === 7 ? '-01' : ''))])
    const min = Math.min(...dates)
    const max = Math.max(...dates)
    return {
      backgroundColor: 'transparent',
      grid: { left: 72, right: 24, top: 24, bottom: 48 },
      xAxis: { type: 'time', name: 'Release date', nameLocation: 'middle', nameGap: 32, ...darkAxis, splitLine: { show: false } },
      yAxis: { type: 'time', name: 'Knowledge cutoff', ...darkAxis },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: Point & { released: string; cutoff: string } } }) =>
          `<b>${p.data.meta.name}</b><br/>released ${p.data.meta.released} · cutoff ${p.data.meta.cutoff}`,
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 9,
          data: pts.map((m) => ({
            value: [
              m.released,
              m.cutoff!.length === 7 ? `${m.cutoff}-01` : m.cutoff,
            ],
            meta: { slug: m.slug, name: m.name, dev: m.dev, released: m.released, cutoff: m.cutoff },
            itemStyle: { color: colorForDark(m.dev), opacity: 0.8 },
          })),
        },
        {
          // cutoff == release diagonal reference
          type: 'line',
          showSymbol: false,
          silent: true,
          data: [
            [min, min],
            [max, max],
          ],
          lineStyle: { color: '#525252', type: 'dashed', width: 1 },
        },
      ],
    }
  }, [models])

  // 3. Open vs closed best score per benchmark (independent results only)
  const gapOption = useMemo<EChartsCoreOption | null>(() => {
    if (!models || !benchmarks) return null
    const benchIds = benchmarks.map((b) => b.id)
    const best = new Map<string, { open: number | null; closed: number | null }>()
    for (const m of models) {
      for (const [bid, s] of Object.entries(m.scores)) {
        if (s.selfReported === 1) continue
        const entry = best.get(bid) ?? { open: null, closed: null }
        if (m.open === 1) entry.open = Math.max(entry.open ?? -Infinity, s.score)
        else entry.closed = Math.max(entry.closed ?? -Infinity, s.score)
        best.set(bid, entry)
      }
    }
    const rows = benchIds
      .filter((id) => best.has(id) && !id.startsWith('lmarena_'))
      .map((id) => ({
        name: benchmarks.find((b) => b.id === id)?.name ?? id,
        ...best.get(id)!,
      }))
    if (rows.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 120, right: 24, top: 40, bottom: 32 },
      legend: { textStyle: { color: '#a3a3a3' }, top: 0 },
      xAxis: { type: 'value', ...darkAxis },
      yAxis: { type: 'category', data: rows.map((r) => r.name), axisLabel: { color: '#d4d4d4', fontSize: 11 } },
      tooltip: { trigger: 'axis' },
      series: [
        {
          name: 'Closed',
          type: 'bar',
          data: rows.map((r) => r.closed),
          itemStyle: { color: '#737373' },
          barMaxWidth: 12,
        },
        {
          name: 'Open weights',
          type: 'bar',
          data: rows.map((r) => r.open),
          itemStyle: { color: '#10b981' },
          barMaxWidth: 12,
        },
      ],
    }
  }, [models, benchmarks])

  const ctxRef = useECharts(ctxOption, goTo)
  const freshRef = useECharts(freshOption, goTo)
  const gapRef = useECharts(gapOption)

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-neutral-100">Landscape</h1>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">
          Context-window arms race
        </h2>
        {ctxOption ? (
          <div ref={ctxRef} className="h-[420px] w-full" />
        ) : (
          <div className="py-16 text-center text-sm text-neutral-500">No data.</div>
        )}
      </div>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">Knowledge freshness</h2>
        <p className="mb-2 text-xs text-neutral-500">
          Dashed line = cutoff equals release date; distance below it is staleness at launch.
        </p>
        {freshOption ? (
          <div ref={freshRef} className="h-[420px] w-full" />
        ) : (
          <div className="py-16 text-center text-sm text-neutral-500">No data.</div>
        )}
      </div>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">
          Open vs closed: best independent score per benchmark
        </h2>
        {gapOption ? (
          <div ref={gapRef} className="h-[420px] w-full" />
        ) : (
          <div className="py-16 text-center text-sm text-neutral-500">No data.</div>
        )}
      </div>
    </div>
  )
}
