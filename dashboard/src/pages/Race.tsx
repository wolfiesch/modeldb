import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useNavigate } from 'react-router'
import {
  loadBenchmarkTimeseries,
  loadElo,
  useData,
  type BenchmarkTimeseriesFile,
  type EloFile,
} from '../lib/data'
import { labLabel } from '../lib/labs'
import { colorForDark, shortName } from '../lib/theme'
import '../lib/useECharts'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsCoreOption } from 'echarts/core'

type EloKind = 'text_overall' | 'text_coding'
type BenchmarkKind = 'coding_agent' | 'reasoning' | 'math' | 'knowledge'
type SeriesKind = EloKind | BenchmarkKind
type BenchmarkKey =
  | 'deepswe'
  | 'swe_bench_verified'
  | 'hle'
  | 'gpqa_diamond'
  | 'frontiermath'
  | 'math_level_5'
  | 'epoch_capabilities_index'
type MetricKind = 'elo' | 'score'
type ValueFormat = 'elo' | 'fractionPercent' | 'percentScore' | 'index'
type RaceDataset = EloFile | BenchmarkTimeseriesFile
type EloSeries = EloFile['series'][number]
type BenchmarkTimeseriesSeries = BenchmarkTimeseriesFile['series'][number]
type RaceSeries = EloSeries | BenchmarkTimeseriesSeries

interface BaseRegime {
  kind: SeriesKind
  label: string
  description: string
  metricName: string
}

interface EloRegime extends BaseRegime {
  source: 'elo'
  eloSeries: EloKind
}

interface BenchmarkRegime extends BaseRegime {
  source: 'benchmark'
  benchmarks: readonly BenchmarkKey[]
}

type Regime = EloRegime | BenchmarkRegime

interface ActiveBenchmarkDataset {
  file: BenchmarkTimeseriesFile
  key: BenchmarkKey
}

interface RaceRow {
  modelId: number
  slug: string
  name: string
  dev: string | null
  value: number
}

const STEP_MS = 800
const TOP_N = 20

const REGIMES = [
  {
    kind: 'text_overall',
    source: 'elo',
    eloSeries: 'text_overall',
    label: 'Overall Preference',
    description: 'LMArena text_overall ELO',
    metricName: 'LMArena ELO',
  },
  {
    kind: 'text_coding',
    source: 'elo',
    eloSeries: 'text_coding',
    label: 'Coding Preference',
    description: 'LMArena text_coding ELO',
    metricName: 'LMArena ELO',
  },
  {
    kind: 'coding_agent',
    source: 'benchmark',
    benchmarks: ['deepswe', 'swe_bench_verified'],
    label: 'Coding Agent',
    description: 'DeepSWE, falling back to SWE-bench Verified',
    metricName: 'Coding agent score',
  },
  {
    kind: 'reasoning',
    source: 'benchmark',
    benchmarks: ['hle', 'gpqa_diamond'],
    label: 'Reasoning',
    description: 'Humanity\'s Last Exam, falling back to GPQA Diamond',
    metricName: 'Reasoning score',
  },
  {
    kind: 'math',
    source: 'benchmark',
    benchmarks: ['frontiermath', 'math_level_5'],
    label: 'Math',
    description: 'FrontierMath, falling back to MATH level 5',
    metricName: 'Math score',
  },
  {
    kind: 'knowledge',
    source: 'benchmark',
    benchmarks: ['epoch_capabilities_index'],
    label: 'Knowledge',
    description: 'Epoch AI capabilities index',
    metricName: 'Capabilities index',
  },
] satisfies readonly Regime[]
const REGIME_BY_KIND: Record<SeriesKind, Regime> = {
  text_overall: REGIMES[0],
  text_coding: REGIMES[1],
  coding_agent: REGIMES[2],
  reasoning: REGIMES[3],
  math: REGIMES[4],
  knowledge: REGIMES[5],
}

const loadOverallElo = () => loadElo('text_overall')
const loadCodingElo = () => loadElo('text_coding')

export default function Race() {
  const [kind, setKind] = useState<SeriesKind>('text_overall')
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const overall = useData(loadOverallElo)
  const coding = useData(loadCodingElo)
  const benchmarkTimeseries = useData(loadBenchmarkTimeseries)
  const navigate = useNavigate()
  const regime = REGIME_BY_KIND[kind]
  const activeBenchmark = useMemo(
    () => (isBenchmarkRegime(regime) ? selectBenchmarkDataset(benchmarkTimeseries.data, regime) : null),
    [benchmarkTimeseries.data, regime],
  )
  const activeData: RaceDataset | null =
    regime.source === 'benchmark'
      ? activeBenchmark?.file ?? null
      : regime.eloSeries === 'text_overall'
        ? overall.data
        : coding.data
  const loading =
    regime.source === 'benchmark'
      ? benchmarkTimeseries.loading
      : regime.eloSeries === 'text_overall'
        ? overall.loading
        : coding.loading
  const error =
    regime.source === 'benchmark'
      ? benchmarkTimeseries.error
      : regime.eloSeries === 'text_overall'
        ? overall.error
        : coding.error
  const metric: MetricKind = regime.source === 'elo' ? 'elo' : 'score'

  const timeline = useMemo(() => (activeData ? weeklyTimeline(activeData) : []), [activeData])
  const currentTime = timeline[index] ?? timeline[0] ?? null

  useEffect(() => {
    setIndex(0)
    setPlaying(false)
  }, [kind])

  useEffect(() => {
    if (index >= timeline.length) setIndex(Math.max(0, timeline.length - 1))
  }, [index, timeline.length])

  useEffect(() => {
    if (!playing || timeline.length < 2) return
    const id = window.setInterval(() => {
      setIndex((current) => (current >= timeline.length - 1 ? 0 : current + 1))
    }, STEP_MS)
    return () => window.clearInterval(id)
  }, [playing, timeline.length])

  const rows = useMemo(() => {
    if (!activeData || currentTime == null) return []
    return topAtTime(activeData, metric, currentTime, TOP_N)
  }, [activeData, currentTime, metric])
  const valueFormat = valueFormatForRows(regime, rows)
  const dateLabel = currentTime == null ? 'No date' : formatDate(currentTime)
  const sourceLabel = activeBenchmark?.key ?? regime.description

  const rowsRef = useRef<RaceRow[]>([])
  rowsRef.current = rows

  const [chartHost, setChartHost] = useState<HTMLDivElement | null>(null)
  const chartInstanceRef = useRef<ECharts | null>(null)
  const resizeObserverRef = useRef<ResizeObserver | null>(null)
  const chartHostRef = useCallback((node: HTMLDivElement | null) => setChartHost(node), [])

  useEffect(() => {
    if (!chartHost) return

    const chart = echarts.init(chartHost, undefined, { renderer: 'canvas' })
    chartInstanceRef.current = chart
    const navigateToRow = (row: RaceRow | null | undefined) => {
      if (row?.slug) navigate(`/models/${encodeURIComponent(row.slug)}`)
    }
    chart.on('click', (params: unknown) => {
      const p = params as { data?: { meta?: RaceRow }; dataIndex?: number }
      navigateToRow(p.data?.meta ?? (p.dataIndex == null ? null : rowsRef.current[p.dataIndex]))
    })
    const handleHostClick = (event: MouseEvent) => {
      const { left, top, height } = chartHost.getBoundingClientRect()
      const x = event.clientX - left
      const y = event.clientY - top
      const rows = rowsRef.current
      const plotTop = 8
      const plotBottom = 42
      const plotHeight = height - plotTop - plotBottom
      const index = Math.floor(((y - plotTop) / plotHeight) * rows.length)
      if (x < 170 || index < 0 || index >= rows.length) return
      navigateToRow(rows[index])
    }
    chartHost.addEventListener('click', handleHostClick)

    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(chartHost)
    resizeObserverRef.current = observer

    const initialRows = rowsRef.current
    if (initialRows.length > 0) {
      chart.resize()
      chart.setOption(raceOption(initialRows, false, regime, valueFormat), { replaceMerge: ['yAxis', 'series'] })
    }

    return () => {
      chartHost.removeEventListener('click', handleHostClick)
      observer.disconnect()
      resizeObserverRef.current = null
      chart.dispose()
      chartInstanceRef.current = null
    }
  }, [chartHost, navigate, regime, valueFormat])

  useEffect(() => {
    const chart = chartInstanceRef.current
    if (!chartHost || !chart || rows.length === 0) return
    chart.resize()
    if (playing) {
      chart.setOption({
        animationDurationUpdate: 650,
        animationEasingUpdate: 'cubicOut',
        xAxis: {
          max: niceAxisMax(rows, valueFormat),
        },
        series: [
          {
            id: 'race',
            data: rows.map((r) => ({
              name: r.name,
              value: r.value,
              meta: r,
              itemStyle: { color: colorForDark(r.dev), opacity: 0.9 },
            })),
          }
        ]
      })
    } else {
      chart.setOption(raceOption(rows, false, regime, valueFormat), {
        replaceMerge: ['yAxis', 'series'],
      })
    }
  }, [chartHost, playing, regime, rows, valueFormat])

  const handleScrub = (event: ChangeEvent<HTMLInputElement>) => {
    const nextIndex = Number(event.target.value)
    setPlaying(false)
    setIndex(nextIndex)

    const nextTime = timeline[nextIndex]
    const chart = chartInstanceRef.current
    if (activeData && nextTime != null && chart) {
      const nextRows = topAtTime(activeData, metric, nextTime, TOP_N)
      const nextValueFormat = valueFormatForRows(regime, nextRows)
      rowsRef.current = nextRows
      chart.resize()
      chart.setOption(raceOption(nextRows, false, regime, nextValueFormat), { replaceMerge: ['yAxis', 'series'] })
    }
  }

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!activeData) return <div className="text-neutral-500">No data found for {regime.label}.</div>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-neutral-100">Capability Regime Race</h1>
          <p className="mt-1 text-xs text-neutral-500">
            Top 20 models by most recent {regime.metricName.toLowerCase()} at each point in time. Click a bar for
            details.
          </p>
        </div>
        <div className="flex flex-wrap overflow-hidden rounded-md border border-neutral-700">
          {REGIMES.map((candidate) => (
            <button
              key={candidate.kind}
              onClick={() => setKind(candidate.kind)}
              className={`px-3 py-1.5 text-xs ${
                kind === candidate.kind
                  ? 'bg-neutral-700 text-white'
                  : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {candidate.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-3xl font-semibold tracking-tight text-neutral-100">{dateLabel}</div>
            <div className="mt-1 text-xs text-neutral-500">
              {sourceLabel} · Frame {timeline.length === 0 ? 0 : index + 1} of {timeline.length}
            </div>
          </div>
          <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-3">
            <button
              onClick={() => setPlaying((value) => !value)}
              disabled={timeline.length < 2}
              className="rounded-md border border-neutral-700 bg-neutral-950 px-4 py-2 text-sm text-neutral-200 hover:border-neutral-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {playing ? 'Pause' : 'Play'}
            </button>
            <input
              type="range"
              min={0}
              max={Math.max(0, timeline.length - 1)}
              value={Math.min(index, Math.max(0, timeline.length - 1))}
              onChange={handleScrub}
              className="h-2 min-w-56 accent-neutral-200"
              aria-label="Race date"
            />
          </div>
        </div>
        {rows.length > 0 ? (
          <div ref={chartHostRef} className="h-[620px] w-full cursor-pointer" />
        ) : (
          <div className="py-16 text-center text-sm text-neutral-500">
            No {regime.metricName.toLowerCase()} data for this date.
          </div>
        )}
      </div>
    </div>
  )
}


function isBenchmarkRegime(regime: Regime): regime is BenchmarkRegime {
  return regime.source === 'benchmark'
}


function selectBenchmarkDataset(
  timeseries: Record<string, BenchmarkTimeseriesFile> | null,
  regime: BenchmarkRegime,
): ActiveBenchmarkDataset | null {
  if (!timeseries) return null
  let bestDataset: ActiveBenchmarkDataset | null = null
  let maxFrames = -1
  for (const key of regime.benchmarks) {
    const file = timeseries[key]
    if (file && file.series.length > 0) {
      const frames = weeklyTimeline(file).length
      if (frames > maxFrames) {
        maxFrames = frames
        bestDataset = { file, key }
      }
    }
  }
  return bestDataset
}

function weeklyTimeline(dataset: RaceDataset): number[] {
  const byWeek = new Map<string, number>()
  for (const series of dataset.series) {
    for (const t of series.t) {
      if (!Number.isFinite(t)) continue
      const key = weekKey(t)
      const previous = byWeek.get(key)
      if (previous == null || t > previous) byWeek.set(key, t)
    }
  }
  return [...byWeek.values()].sort((a, b) => a - b)
}

function raceOption(
  rows: RaceRow[],
  animateUpdate: boolean,
  regime: Regime,
  valueFormat: ValueFormat,
): EChartsCoreOption {
  return {
    backgroundColor: 'transparent',
    animationDurationUpdate: animateUpdate ? 650 : 0,
    animationEasingUpdate: 'cubicOut',
    grid: { left: 170, right: 44, top: 8, bottom: 42 },
    xAxis: {
      id: 'race-x',
      type: 'value',
      name: regime.metricName,
      min: 0,
      max: niceAxisMax(rows, valueFormat),
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: {
        color: '#a3a3a3',
        formatter: (value: number) => formatMetric(value, valueFormat),
      },
      nameTextStyle: { color: '#737373' },
      splitLine: { lineStyle: { color: '#262626' } },
    },
    yAxis: {
      id: 'race-y',
      type: 'category',
      inverse: true,
      axisLabel: { color: '#d4d4d4', fontSize: 11 },
      axisTick: { show: false },
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (p: { data: { meta: RaceRow } }) => {
        const d = p.data.meta
        return `<b>${d.name}</b><br/>${regime.metricName}: ${formatMetric(d.value, valueFormat)}<br/>${labLabel(d.dev)}`
      },
    },
    series: [
      {
        id: 'race',
        type: 'bar',
        barMaxWidth: 18,
        realtimeSort: true,
        label: {
          show: true,
          position: 'right',
          color: '#d4d4d4',
          formatter: (p: { value: number }) => formatMetric(p.value, valueFormat),
        },
        data: rows.map((r) => ({
          name: r.name,
          value: r.value,
          meta: r,
          itemStyle: { color: colorForDark(r.dev), opacity: 0.9 },
        })),
      },
    ],
  }
}

function weekKey(t: number): string {
  const date = new Date(t)
  const year = date.getUTCFullYear()
  const start = Date.UTC(year, 0, 1)
  const day = Math.floor((Date.UTC(year, date.getUTCMonth(), date.getUTCDate()) - start) / 86400000)
  return `${year}-${Math.floor(day / 7)}`
}

function topAtTime(dataset: RaceDataset, metric: MetricKind, t: number, limit: number): RaceRow[] {
  const meta = new Map(dataset.models.map((model) => [model.id, model]))
  const bestByModel = new Map<number, RaceRow>()

  for (const series of dataset.series) {
    const point = latestPointAtOrBefore(series, metric, t)
    const model = meta.get(series.modelId)
    if (point == null || !model) continue

    const existing = bestByModel.get(series.modelId)
    if (existing != null && existing.value >= point) continue
    bestByModel.set(series.modelId, {
      modelId: series.modelId,
      slug: model.slug,
      name: shortName(model.slug),
      dev: model.dev,
      value: point,
    })
  }

  return [...bestByModel.values()].sort((a, b) => b.value - a.value).slice(0, limit)
}

function latestPointAtOrBefore(series: RaceSeries, metric: MetricKind, target: number): number | null {
  if (metric === 'elo' && isEloSeries(series)) return latestAtOrBefore(series.t, series.elo, target)
  if (metric === 'score' && isBenchmarkSeries(series)) return latestAtOrBefore(series.t, series.score, target)
  return null
}

function isEloSeries(series: RaceSeries): series is EloSeries {
  return 'elo' in series
}

function isBenchmarkSeries(series: RaceSeries): series is BenchmarkTimeseriesSeries {
  return 'score' in series
}

function latestAtOrBefore(times: number[], values: number[], target: number): number | null {
  let lo = 0
  let hi = times.length - 1
  let best = -1
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2)
    if (times[mid] <= target) {
      best = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  const value = values[best]
  return Number.isFinite(value) ? value : null
}

function valueFormatForRows(regime: Regime, rows: RaceRow[]): ValueFormat {
  if (regime.source === 'elo') return 'elo'
  if (regime.kind === 'knowledge') return 'index'
  const max = Math.max(0, ...rows.map((row) => row.value))
  return max <= 1.5 ? 'fractionPercent' : 'percentScore'
}

function formatMetric(value: number, format: ValueFormat): string {
  switch (format) {
    case 'elo':
      return String(Math.round(value))
    case 'fractionPercent':
      return `${(value * 100).toFixed(1)}%`
    case 'percentScore':
      return `${value.toFixed(1)}%`
    case 'index':
      return value >= 100 ? value.toFixed(0) : value.toFixed(1)
  }
}

function niceAxisMax(rows: RaceRow[], format: ValueFormat): number | undefined {
  const max = Math.max(0, ...rows.map((row) => row.value))
  if (max <= 0) return undefined
  if (format === 'fractionPercent') return Math.min(1, Math.ceil(max * 10) / 10)
  const step = format === 'elo' || format === 'index' ? 100 : 10
  return Math.ceil(max / step) * step
}

function formatDate(t: number): string {
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(t))
}
