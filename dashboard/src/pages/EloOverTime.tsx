import { useCallback, useEffect, useMemo, useState } from 'react'
import { loadElo, loadModels, useData, loadBenchmarkTimeseries } from '../lib/data'
import LabLogo from '../components/LabLogo'
import { colorForDark, shortName } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import { useSearchParams } from 'react-router'
import type { EChartsCoreOption } from 'echarts/core'

interface TimeseriesSeries {
  modelId: number
  t: number[]
  elo?: number[]
  score?: number[]
  rank: Array<number | null>
}

interface TimeseriesDataset {
  models: Array<{ id: number; slug: string; dev: string | null }>
  series: TimeseriesSeries[]
}

interface Point {
  t: number
  score: number
  modelId: number
}

function selectedModelsFromParam(params: URLSearchParams): Set<number> | null {
  if (!params.has('m')) return null
  const ids = (params.get('m') ?? '')
    .split(',')
    .map((id) => Number(id))
    .filter((id) => Number.isInteger(id))
  return new Set(ids)
}

const DEFAULT_BENCHMARK_ID = 'lmarena_text_overall'

const TIMELINE_BENCHMARKS = [
  { id: 'lmarena_text_overall', label: 'LMArena Text Overall', category: 'arena' },
  { id: 'lmarena_text_coding', label: 'LMArena Text Coding', category: 'arena' },
  { id: 'gpqa_diamond', label: 'GPQA Diamond', category: 'reasoning' },
  { id: 'hle', label: 'HLE (Reasoning)', category: 'reasoning' },
  { id: 'scicode', label: 'SciCode', category: 'coding' },
  { id: 'math_level_5', label: 'MATH L5', category: 'math' },
  { id: 'frontiermath', label: 'FrontierMath', category: 'math' },
  { id: 'swe_bench_verified', label: 'SWE Verified', category: 'coding' },
  { id: 'deepswe', label: 'DeepSWE', category: 'coding' },
  { id: 'aider_polyglot', label: 'Aider Polyglot', category: 'coding' },
  { id: 'lcr', label: 'LCR (Coding)', category: 'coding' },
  { id: 'tau2', label: 'TAU-Agent', category: 'agentic' },
  { id: 'terminalbench_hard', label: 'TerminalBench', category: 'agentic' },
  { id: 'epoch_capabilities_index', label: 'Epoch Capabilities Index', category: 'composite' },
]

export default function EloOverTime() {
  const [params, setParams] = useSearchParams()
  const [benchId, setBenchId] = useState<string>(() => params.get('b') ?? DEFAULT_BENCHMARK_ID)
  
  const { data: eloOverall, loading: overallLoading } = useData(useCallback(() => loadElo('text_overall'), []))
  const { data: eloCoding, loading: codingLoading } = useData(useCallback(() => loadElo('text_coding'), []))
  const { data: timeseries, loading: timeseriesLoading } = useData(loadBenchmarkTimeseries)
  const { data: models, loading: modelsLoading } = useData(loadModels)

  const [selected, setSelected] = useState<Set<number> | null>(() => selectedModelsFromParam(params))
  const [search, setSearch] = useState('')

  useEffect(() => {
    const next = new URLSearchParams()
    if (benchId !== DEFAULT_BENCHMARK_ID) next.set('b', benchId)
    if (selected) next.set('m', [...selected].join(','))
    setParams(next, { replace: true })
  }, [benchId, selected, setParams])

  const activeDataset = useMemo<TimeseriesDataset | null>(() => {
    if (benchId === 'lmarena_text_overall') return eloOverall
    if (benchId === 'lmarena_text_coding') return eloCoding
    return timeseries?.[benchId] ?? null
  }, [benchId, eloOverall, eloCoding, timeseries])

  const nameOf = useMemo(() => {
    const m = new Map<number, string>()
    for (const model of models ?? []) m.set(model.id, model.name)
    return m
  }, [models])

  // Get active models ranked by latest value.
  const ranked = useMemo(() => {
    if (!activeDataset) return []
    return [...activeDataset.series]
      .map((s) => {
        const scores = s.elo ?? s.score ?? []
        return {
          modelId: s.modelId,
          latest: scores[scores.length - 1] ?? 0,
        }
      })
      .sort((a, b) => b.latest - a.latest)
  }, [activeDataset])

  const activeIds = useMemo(() => {
    if (selected) return selected
    return new Set(ranked.slice(0, 15).map((r) => r.modelId))
  }, [selected, ranked])

  // Compute the frontier envelope and active series.
  const envelopeAndLines = useMemo(() => {
    if (!activeDataset || !models) return null

    // 1. Gather all raw points.
    const allPoints: Point[] = []
    for (const s of activeDataset.series) {
      const scores = s.elo ?? s.score ?? []
      s.t.forEach((t, idx) => {
        const score = scores[idx]
        if (score !== undefined) {
          allPoints.push({ t, score, modelId: s.modelId })
        }
      })
    }

    if (allPoints.length === 0) return null

    // 2. Extract unique sorted timestamps.
    const times = [...new Set(allPoints.map((p) => p.t))].sort((a, b) => a - b)

    // 3. For each timestamp, find active scores (latest score at or before timestamp).
    const maxPath: Array<[number, number]> = []
    const medianPath: Array<[number, number]> = []
    const q1Path: Array<[number, number]> = []

    const lastSeenByModel = new Map<number, number>()
    const modelMeta = new Map(models.map((m) => [m.id, m]))

    // Keep track of which model resets/defines the maximum frontier at each step.
    const frontierResets: Array<{ t: number; modelName: string; score: number }> = []
    let currentGlobalMax = -Infinity

    for (const t of times) {
      // Update our last seen map with points at exactly this timestamp.
      allPoints
        .filter((p) => p.t === t)
        .forEach((p) => lastSeenByModel.set(p.modelId, p.score))

      const activeScores = [...lastSeenByModel.values()].sort((a, b) => b - a)

      if (activeScores.length > 0) {
        const maxVal = activeScores[0]
        
        // Find which model owns this maximum value.
        const maxPoint = allPoints.find((p) => p.t === t && p.score === maxVal)
        if (maxPoint && maxVal > currentGlobalMax) {
          currentGlobalMax = maxVal
          const meta = modelMeta.get(maxPoint.modelId)
          if (meta) {
            frontierResets.push({
              t,
              modelName: meta.name,
              score: maxVal,
            })
          }
        }

        const midIndex = Math.floor(activeScores.length / 2)
        const medianVal = activeScores.length % 2 === 0
          ? (activeScores[midIndex - 1] + activeScores[midIndex]) / 2
          : activeScores[midIndex]

        const q1Index = Math.floor(activeScores.length * 0.75)
        const q1Val = activeScores[q1Index] ?? activeScores[activeScores.length - 1]

        maxPath.push([t, maxVal])
        medianPath.push([t, medianVal])
        q1Path.push([t, q1Val])
      }
    }

    return {
      times,
      maxPath,
      medianPath,
      q1Path,
      frontierResets,
    }
  }, [activeDataset, models])

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!activeDataset || !envelopeAndLines) return null
    
    const devOf = new Map(activeDataset.models.map((m) => [m.id, m.dev]))

    // Selected model lines.
    const lineSeries = activeDataset.series
      .filter((s) => activeIds.has(s.modelId))
      .map((s) => {
        const scores = s.elo ?? s.score ?? []
        return {
          name: nameOf.get(s.modelId) ?? shortName(String(s.modelId)),
          type: 'line' as const,
          showSymbol: false,
          sampling: 'lttb' as const,
          z: 3,
          data: s.t.map((t, idx) => [t, scores[idx]]),
          lineStyle: { width: 2, color: colorForDark(devOf.get(s.modelId)) },
          itemStyle: { color: colorForDark(devOf.get(s.modelId)) },
          emphasis: { lineStyle: { width: 3.5 }, focus: 'series' as const },
        }
      })

    // Shaded Envelope Series.
    // Stacked area style:
    // Base series = Q1 (lower bound), colored transparent.
    // Top series = Max (upper bound), stacked, with areaStyle colored.
    const envelopeSeries = [
      {
        name: 'Lower Quartile (25%)',
        type: 'line' as const,
        stack: 'frontier-envelope',
        showSymbol: false,
        silent: true,
        z: 1,
        lineStyle: { opacity: 0 },
        data: envelopeAndLines.q1Path,
      },
      {
        name: 'Frontier Envelope (Max)',
        type: 'line' as const,
        stack: 'frontier-envelope',
        showSymbol: false,
        z: 1,
        lineStyle: { color: 'rgba(16, 185, 129, 0.3)', width: 1, type: 'dashed' as const },
        areaStyle: { color: 'rgba(16, 185, 129, 0.08)' },
        data: envelopeAndLines.maxPath.map((pt, idx) => {
          const q1Pt = envelopeAndLines.q1Path[idx]
          const q1Val = q1Pt ? q1Pt[1] : 0
          return [pt[0], pt[1] - q1Val]
        }),
      },
      {
        name: 'Median Score (50%)',
        type: 'line' as const,
        showSymbol: false,
        z: 2,
        lineStyle: { color: 'rgba(16, 185, 129, 0.6)', width: 1.5, type: 'dotted' as const },
        data: envelopeAndLines.medianPath,
      }
    ]

    // Annotations for frontier resets.
    const markPointData = envelopeAndLines.frontierResets.map((reset) => ({
      name: reset.modelName,
      value: reset.modelName,
      coord: [reset.t, reset.score],
      symbolSize: 8,
      itemStyle: { color: '#10b981' },
      label: {
        show: true,
        position: 'top',
        formatter: '{b}',
        color: '#a3a3a3',
        fontSize: 10,
        backgroundColor: '#171717',
        borderColor: '#262626',
        borderWidth: 1,
        borderRadius: 4,
        padding: [2, 4],
      },
    }))

    const maxLineWithMarks = {
      name: 'Ecosystem Maximum',
      type: 'line' as const,
      showSymbol: false,
      z: 2,
      lineStyle: { color: '#10b981', width: 2 },
      data: envelopeAndLines.maxPath,
      markPoint: {
        data: markPointData,
      },
    }

    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 32, top: 32, bottom: 88 },
      xAxis: {
        type: 'time',
        axisLabel: { color: '#a3a3a3' },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        name: benchId.startsWith('lmarena') ? 'ELO' : 'Score',
        axisLabel: { color: '#a3a3a3' },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      dataZoom: [
        { type: 'inside', xAxisIndex: 0 },
        { type: 'slider', xAxisIndex: 0, bottom: 16, height: 24 },
      ],
      tooltip: {
        trigger: 'axis',
        order: 'valueDesc',
        confine: true,
        formatter: (params: unknown) => {
          const list = params as Array<{ seriesName: string; value: [number, number]; marker: string }>
          if (!list || list.length === 0) return ''
          const date = new Date(list[0].value[0]).toLocaleDateString()
          let out = `<b>${date}</b><br/>`
          list.forEach((p) => {
            if (p.seriesName.includes('Lower') || p.seriesName.includes('Envelope')) return
            const val = p.value[1]
            out += `${p.marker} ${p.seriesName}: ${Math.round(val)}<br/>`
          })
          return out
        },
      },
      series: [...envelopeSeries, maxLineWithMarks, ...lineSeries],
    }
  }, [activeDataset, activeIds, envelopeAndLines, nameOf, benchId])

  const chartRef = useECharts(option)

  const searchResults = useMemo(() => {
    if (!activeDataset || !search.trim()) return []
    const needle = search.trim().toLowerCase()
    return activeDataset.models
      .filter((m) => m.slug.toLowerCase().includes(needle))
      .slice(0, 12)
  }, [activeDataset, search])

  const toggle = (id: number) => {
    setSelected((cur) => {
      const next = new Set(cur ?? activeIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const isDataLoading = overallLoading || codingLoading || timeseriesLoading || modelsLoading

  if (isDataLoading) return <div className="text-neutral-500">Loading…</div>
  if (!activeDataset) return null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-neutral-100">Frontier Envelope over Time</h1>
          <p className="text-xs text-neutral-500 mt-1">
            See how the maximum capability frontier expands over time, with quartile bands (envelope) representing the broader model ecosystem.
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-neutral-500" htmlFor="timeline-benchmark">Benchmark</label>
          <select
            id="timeline-benchmark"
            value={benchId}
            onChange={(e) => {
              setBenchId(e.target.value)
              setSelected(null) // reset to default cohort for this benchmark
            }}
            className="rounded border border-neutral-700 bg-neutral-950 px-2.5 py-1.5 text-xs text-neutral-200"
          >
            {TIMELINE_BENCHMARKS.map((b) => (
              <option key={b.id} value={b.id}>
                {b.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div ref={chartRef} className="h-[480px] w-full" />
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-neutral-200">Highlight Models</h2>
          <button
            onClick={() => setSelected(new Set())}
            className="text-xs text-neutral-500 hover:text-neutral-300"
          >
            Clear Selected
          </button>
        </div>

        <input
          type="text"
          placeholder="Search models to highlight..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="mb-4 w-full rounded border border-neutral-800 bg-neutral-950 px-3 py-2 text-xs text-neutral-200 placeholder-neutral-600 focus:border-neutral-700 focus:outline-none"
        />

        {searchResults.length > 0 && (
          <div className="mb-4 rounded border border-neutral-800 bg-neutral-950 p-2">
            <div className="text-[10px] uppercase tracking-wider text-neutral-500 mb-1 px-1">Search Results</div>
            <div className="flex flex-wrap gap-1.5">
              {searchResults.map((m) => (
                <button
                  key={m.id}
                  onClick={() => toggle(m.id)}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs border ${
                    activeIds.has(m.id)
                      ? 'border-neutral-200 bg-neutral-800 text-white'
                      : 'border-neutral-800 bg-neutral-900 text-neutral-400 hover:border-neutral-700'
                  }`}
                >
                  <LabLogo dev={m.dev} size={12} showLabel labelClassName="max-w-28 truncate" />
                  <span className="opacity-50">/</span>
                  <span>{shortName(m.slug)}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="space-y-3">
          <div className="text-[10px] uppercase tracking-wider text-neutral-500 px-1">Active / Top Models</div>
          <div className="flex flex-wrap gap-1.5">
            {ranked.map((r) => {
              const m = activeDataset.models.find((item) => item.id === r.modelId)
              if (!m) return null
              const isSelected = activeIds.has(r.modelId)
              return (
                <button
                  key={r.modelId}
                  onClick={() => toggle(r.modelId)}
                  className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-xs border transition-all`}
                  style={{
                    borderColor: isSelected ? colorForDark(m.dev) : 'rgba(64,64,64,0.3)',
                    backgroundColor: isSelected ? 'rgba(64,64,64,0.1)' : undefined,
                    color: isSelected ? '#fff' : '#8c8c8c',
                  }}
                >
                  <LabLogo dev={m.dev} size={12} showLabel labelClassName="max-w-24 truncate" />
                  <span className="opacity-50">/</span>
                  <span>{shortName(m.slug)}</span>
                  <span className="ml-1 opacity-70 font-semibold">{Math.round(r.latest)}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
