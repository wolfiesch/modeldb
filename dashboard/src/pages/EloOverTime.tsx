import { useCallback, useMemo, useState } from 'react'
import { loadElo, loadModels, useData, type EloFile } from '../lib/data'
import { colorForDark, shortName } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

type SeriesKind = 'text_overall' | 'text_coding'

export default function EloOverTime() {
  const [kind, setKind] = useState<SeriesKind>('text_overall')
  const loader = useCallback(() => loadElo(kind), [kind])
  const { data: elo, loading, error } = useData(loader)
  const { data: models } = useData(loadModels)
  const [selected, setSelected] = useState<Set<number> | null>(null) // null = default top 25
  const [search, setSearch] = useState('')

  const nameOf = useMemo(() => {
    const m = new Map<number, string>()
    for (const model of models ?? []) m.set(model.id, model.name)
    return m
  }, [models])

  // Latest-ELO ranking of all models in this file.
  const ranked = useMemo(() => {
    if (!elo) return []
    return [...elo.series]
      .map((s) => ({ modelId: s.modelId, latest: s.elo[s.elo.length - 1] ?? 0 }))
      .sort((a, b) => b.latest - a.latest)
  }, [elo])

  const activeIds = useMemo(() => {
    if (selected) return selected
    return new Set(ranked.slice(0, 25).map((r) => r.modelId))
  }, [selected, ranked])

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (!elo) return null
    const devOf = new Map(elo.models.map((m) => [m.id, m.dev]))
    const series = elo.series
      .filter((s) => activeIds.has(s.modelId))
      .map((s) => ({
        name: nameOf.get(s.modelId) ?? shortName(String(s.modelId)),
        type: 'line' as const,
        showSymbol: false,
        sampling: 'lttb' as const,
        data: s.t.map((t, i) => [t, s.elo[i]]),
        lineStyle: { width: 1.5, color: colorForDark(devOf.get(s.modelId)) },
        itemStyle: { color: colorForDark(devOf.get(s.modelId)) },
        emphasis: { focus: 'series' as const },
      }))
    if (series.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 24, top: 16, bottom: 88 },
      xAxis: {
        type: 'time',
        axisLabel: { color: '#a3a3a3' },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        name: 'ELO',
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
        valueFormatter: (v: number) => String(Math.round(v)),
      },
      series,
    }
  }, [elo, activeIds, nameOf])

  const chartRef = useECharts(option)

  const searchResults = useMemo(() => {
    if (!elo || !search.trim()) return []
    const needle = search.trim().toLowerCase()
    return elo.models
      .filter((m) => m.slug.toLowerCase().includes(needle))
      .slice(0, 12)
  }, [elo, search])

  const toggle = (id: number) => {
    setSelected((cur) => {
      const next = new Set(cur ?? activeIds)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!elo) return null

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-100">Arena ELO over time</h1>
        <div className="flex overflow-hidden rounded-md border border-neutral-700">
          {(['text_overall', 'text_coding'] as const).map((k) => (
            <button
              key={k}
              onClick={() => {
                setKind(k)
                setSelected(null)
              }}
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
        <div className="relative">
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Add/remove model…"
            className="w-64 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-1.5 text-xs text-neutral-200 placeholder-neutral-600 outline-none focus:border-neutral-500"
          />
          {searchResults.length > 0 && (
            <div className="absolute z-10 mt-1 w-full rounded-md border border-neutral-700 bg-neutral-900 shadow-xl">
              {searchResults.map((m) => (
                <button
                  key={m.id}
                  onClick={() => toggle(m.id)}
                  className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs text-neutral-300 hover:bg-neutral-800"
                >
                  <span>{nameOf.get(m.id) ?? m.slug}</span>
                  <span className="text-neutral-600">
                    {activeIds.has(m.id) ? 'remove' : 'add'}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <button
          onClick={() => setSelected(null)}
          className="rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-400 hover:border-neutral-500"
        >
          Reset to top 25
        </button>
        <span className="text-xs text-neutral-600">{activeIds.size} lines</span>
      </div>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div ref={chartRef} className="h-[560px] w-full" />
      </div>
      <ActiveChips elo={elo} activeIds={activeIds} nameOf={nameOf} onToggle={toggle} />
    </div>
  )
}

function ActiveChips({
  elo,
  activeIds,
  nameOf,
  onToggle,
}: {
  elo: EloFile
  activeIds: Set<number>
  nameOf: Map<number, string>
  onToggle: (id: number) => void
}) {
  const active = elo.models.filter((m) => activeIds.has(m.id))
  return (
    <div className="flex flex-wrap gap-1.5">
      {active.map((m) => (
        <button
          key={m.id}
          onClick={() => onToggle(m.id)}
          className="group flex items-center gap-1.5 rounded-full border border-neutral-800 bg-neutral-900 px-2.5 py-1 text-[11px] text-neutral-300 hover:border-neutral-600"
          title="Remove from chart"
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ backgroundColor: colorForDark(m.dev) }}
          />
          {nameOf.get(m.id) ?? m.slug}
          <span className="text-neutral-600 group-hover:text-neutral-400">×</span>
        </button>
      ))}
    </div>
  )
}
