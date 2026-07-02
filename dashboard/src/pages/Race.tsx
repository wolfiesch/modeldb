import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useNavigate } from 'react-router'
import { loadElo, useData, type EloFile } from '../lib/data'
import { labLabel } from '../lib/labs'
import { colorForDark, shortName } from '../lib/theme'
import '../lib/useECharts'
import * as echarts from 'echarts/core'
import type { ECharts, EChartsCoreOption } from 'echarts/core'

type SeriesKind = 'text_overall' | 'text_coding'

interface RaceRow {
  modelId: number
  slug: string
  name: string
  dev: string | null
  elo: number
}

const STEP_MS = 180
const TOP_N = 20

const loadOverallElo = () => loadElo('text_overall')
const loadCodingElo = () => loadElo('text_coding')

export default function Race() {
  const [kind, setKind] = useState<SeriesKind>('text_overall')
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const overall = useData(loadOverallElo)
  const coding = useData(loadCodingElo)
  const navigate = useNavigate()
  const elo = kind === 'text_overall' ? overall.data : coding.data
  const loading = overall.loading || coding.loading
  const error = overall.error ?? coding.error

  const timeline = useMemo(() => (elo ? weeklyTimeline(elo) : []), [elo])
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
    if (!elo || currentTime == null) return []
    return topAtTime(elo, currentTime, TOP_N)
  }, [elo, currentTime])

  const dateLabel = currentTime == null ? 'No date' : formatDate(currentTime)

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
      chart.setOption(raceOption(initialRows, false), { replaceMerge: ['yAxis', 'series'] })
    }

    return () => {
      chartHost.removeEventListener('click', handleHostClick)
      observer.disconnect()
      resizeObserverRef.current = null
      chart.dispose()
      chartInstanceRef.current = null
    }
  }, [chartHost, navigate])

  useEffect(() => {
    const chart = chartInstanceRef.current
    if (!chartHost || !chart || rows.length === 0) return
    chart.resize()
    chart.setOption(raceOption(rows, playing), { replaceMerge: playing ? ['yAxis'] : ['yAxis', 'series'] })
  }, [chartHost, playing, rows])

  const handleScrub = (event: ChangeEvent<HTMLInputElement>) => {
    const nextIndex = Number(event.target.value)
    setPlaying(false)
    setIndex(nextIndex)

    const nextTime = timeline[nextIndex]
    const chart = chartInstanceRef.current
    if (elo && nextTime != null && chart) {
      const nextRows = topAtTime(elo, nextTime, TOP_N)
      rowsRef.current = nextRows
      chart.resize()
      chart.setOption(raceOption(nextRows, false), { replaceMerge: ['yAxis', 'series'] })
    }
  }

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!elo) return null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-neutral-100">Arena ELO race</h1>
          <p className="mt-1 text-xs text-neutral-500">
            Top 20 models by most recent ELO at each point in time. Click a bar for details.
          </p>
        </div>
        <div className="flex overflow-hidden rounded-md border border-neutral-700">
          {(['text_overall', 'text_coding'] as const).map((k) => (
            <button
              key={k}
              onClick={() => setKind(k)}
              className={`px-3 py-1.5 text-xs ${
                kind === k
                  ? 'bg-neutral-700 text-white'
                  : 'bg-neutral-900 text-neutral-400 hover:text-neutral-200'
              }`}
            >
              {k === 'text_overall' ? 'Text overall' : 'Text coding'}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="text-3xl font-semibold tracking-tight text-neutral-100">{dateLabel}</div>
            <div className="mt-1 text-xs text-neutral-500">
              Frame {timeline.length === 0 ? 0 : index + 1} of {timeline.length}
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
          <div className="py-16 text-center text-sm text-neutral-500">No ELO data for this date.</div>
        )}
      </div>
    </div>
  )
}

function weeklyTimeline(elo: EloFile): number[] {
  const byWeek = new Map<string, number>()
  for (const series of elo.series) {
    for (const t of series.t) {
      if (!Number.isFinite(t)) continue
      const key = weekKey(t)
      const previous = byWeek.get(key)
      if (previous == null || t > previous) byWeek.set(key, t)
    }
  }
  return [...byWeek.values()].sort((a, b) => a - b)
}
function raceOption(rows: RaceRow[], animateUpdate: boolean): EChartsCoreOption {
  return {
    backgroundColor: 'transparent',
    animationDurationUpdate: animateUpdate ? 150 : 0,
    animationEasingUpdate: 'linear',
    grid: { left: 170, right: 44, top: 8, bottom: 42 },
    xAxis: {
      id: 'race-x',
      type: 'value',
      name: 'LMArena ELO',
      min: 0,
      nameLocation: 'middle',
      nameGap: 28,
      axisLabel: { color: '#a3a3a3' },
      nameTextStyle: { color: '#737373' },
      splitLine: { lineStyle: { color: '#262626' } },
    },
    yAxis: {
      id: 'race-y',
      type: 'category',
      inverse: true,
      data: rows.map((r) => r.name),
      axisLabel: { color: '#d4d4d4', fontSize: 11 },
      axisTick: { show: false },
    },
    tooltip: {
      trigger: 'item',
      confine: true,
      formatter: (p: { data: { meta: RaceRow } }) => {
        const d = p.data.meta
        return `<b>${d.name}</b><br/>ELO ${Math.round(d.elo)}<br/>${labLabel(d.dev)}`
      },
    },
    series: [
      {
        id: 'race',
        type: 'bar',
        barMaxWidth: 18,
        label: {
          show: true,
          position: 'right',
          color: '#d4d4d4',
          formatter: (p: { value: number }) => String(Math.round(p.value)),
        },
        data: rows.map((r) => ({
          name: r.name,
          value: r.elo,
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

function topAtTime(elo: EloFile, t: number, limit: number): RaceRow[] {
  const meta = new Map(elo.models.map((model) => [model.id, model]))
  return elo.series
    .map((series) => {
      const point = latestAtOrBefore(series.t, series.elo, t)
      const model = meta.get(series.modelId)
      if (point == null || !model) return null
      return {
        modelId: series.modelId,
        slug: model.slug,
        name: shortName(model.slug),
        dev: model.dev,
        elo: point,
      }
    })
    .filter((row): row is RaceRow => row != null)
    .sort((a, b) => b.elo - a.elo)
    .slice(0, limit)
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

function formatDate(t: number): string {
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(t))
}
