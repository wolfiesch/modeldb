import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import LabLogo from '../components/LabLogo'
import { loadElo, loadModels, useData, type Model } from '../lib/data'
import { labLabel, labSearchValues } from '../lib/labs'
import { colorForDark } from '../lib/theme'

const loadOverallElo = () => loadElo('text_overall')
const MS_PER_DAY = 24 * 60 * 60 * 1000

interface TimelineRow {
  model: Model
  releaseMs: number
  endMs: number
  released: string
  lastSeen: string
  deprecated: boolean
}

function parseDateMs(value: string | null): number | null {
  if (!value) return null
  const ms = Date.parse(value)
  return Number.isFinite(ms) ? ms : null
}

function formatDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

function percent(ms: number, min: number, span: number): number {
  return ((ms - min) / span) * 100
}

export default function Timeline() {
  const { data: models, loading, error } = useData(loadModels)
  const { data: elo, loading: eloLoading, error: eloError } = useData(loadOverallElo)
  const navigate = useNavigate()
  const [devFilter, setDevFilter] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const lastSeenByModel = useMemo(() => {
    const map = new Map<number, number>()
    for (const series of elo?.series ?? []) {
      const last = series.t.at(-1)
      if (last != null) map.set(series.modelId, last)
    }
    return map
  }, [elo])

  const allRows = useMemo<TimelineRow[]>(() => {
    if (!models) return []
    return models
      .map((model) => {
        const releaseMs = parseDateMs(model.released)
        if (releaseMs == null) return null
        const lastSeen = lastSeenByModel.get(model.id)
        const rawEndMs = lastSeen ?? releaseMs + 90 * MS_PER_DAY
        const endMs = Math.max(rawEndMs, releaseMs + MS_PER_DAY)
        const stability = model.stability?.toLowerCase()
        return {
          model,
          releaseMs,
          endMs,
          released: formatDate(releaseMs),
          lastSeen: formatDate(endMs),
          deprecated: stability === 'deprecated' || stability === 'retired',
        }
      })
      .filter((row): row is TimelineRow => row != null)
      .sort((a, b) => b.releaseMs - a.releaseMs)
  }, [models, lastSeenByModel])

  const devs = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of allRows) {
      if (row.model.dev) counts.set(row.model.dev, (counts.get(row.model.dev) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([dev]) => dev)
  }, [allRows])

  const filteredRows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return allRows.filter((row) => {
      if (devFilter && row.model.dev !== devFilter) return false
      if (!q) return true
      const labValues = labSearchValues(row.model.dev, row.model.devName)
      return [
        row.model.name,
        row.model.slug,
        row.model.dev,
        row.model.devName,
        row.model.family,
        ...labValues,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(q))
    })
  }, [allRows, devFilter, query])

  const visible = filteredRows

  const scale = useMemo(() => {
    const rows = filteredRows.length > 0 ? filteredRows : allRows
    const min = Math.min(...rows.map((row) => row.releaseMs))
    const max = Math.max(...rows.map((row) => row.endMs))
    const span = Math.max(max - min, MS_PER_DAY)
    return { min, max, span }
  }, [allRows, filteredRows])

  if (loading || eloLoading) {
    return (
      <div className="flex min-h-[400px] flex-col items-center justify-center space-y-4">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-neutral-800 border-t-neutral-400" />
        <span className="text-xs text-neutral-500">Loading timeline...</span>
      </div>
    )
  }
  if (error || eloError) return <div className="text-red-400">{error ?? eloError}</div>
  if (!models || !elo) return null

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h1 className="mr-4 text-base font-semibold text-neutral-100">Model lifespan timeline</h1>
          {devs.map((dev) => (
            <button
              key={dev}
              onClick={() => {
                setDevFilter((cur) => (cur === dev ? null : dev))
              }}
              className={`rounded-full border px-3 py-1 text-xs ${
                devFilter === dev
                  ? 'border-neutral-300 bg-neutral-800 text-white'
                  : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
              }`}
              style={{ borderColor: devFilter === dev ? colorForDark(dev) : undefined }}
            >
              <LabLogo dev={dev} size={16} showLabel labelClassName="truncate" />
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <input
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
            }}
            placeholder="Search model, developer, or family…"
            className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-200 placeholder-neutral-600 outline-none focus:border-neutral-500 sm:w-96"
          />
          <div className="text-xs text-neutral-500">
            {filteredRows.length} of {allRows.length} released models
          </div>
        </div>
      </div>

      {filteredRows.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 py-16 text-center text-neutral-500">
          No models match.
        </div>
      ) : (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
          <div className="mb-4 grid grid-cols-[minmax(11rem,15rem)_1fr] gap-4 text-xs text-neutral-500">
            <div>Model</div>
            <div className="flex justify-between">
              <span>{formatDate(scale.min)}</span>
              <span>{formatDate(scale.max)}</span>
            </div>
          </div>

          <div className="space-y-1">
            {visible.map((row) => {
              const left = percent(row.releaseMs, scale.min, scale.span)
              const width = Math.max(percent(row.endMs, scale.min, scale.span) - left, 0)
              const title = `${row.model.name}\nReleased: ${row.released}\nLast seen: ${row.lastSeen}`
              return (
                <button
                  key={row.model.id}
                  type="button"
                  title={title}
                  onClick={() => navigate(`/models/${encodeURIComponent(row.model.slug)}`)}
                  className="grid w-full grid-cols-[minmax(11rem,15rem)_1fr] items-center gap-4 rounded-md px-2 py-1 text-left hover:bg-neutral-800/60"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm text-neutral-100">{row.model.name}</div>
                    <div className="flex min-w-0 items-center gap-1.5 text-xs text-neutral-500">
                      <LabLogo
                        dev={row.model.dev}
                        devName={row.model.devName}
                        size={16}
                        showLabel
                        title={labLabel(row.model.dev, row.model.devName)}
                        className="min-w-0 gap-1.5"
                        labelClassName="truncate"
                      />
                      <span className="shrink-0">· {row.released}</span>
                    </div>
                  </div>
                  <div className="relative h-8 overflow-hidden rounded-md border border-neutral-800 bg-neutral-950">
                    <div className="absolute inset-y-0 left-0 border-l border-neutral-800/70" />
                    <div className="absolute inset-y-0 right-0 border-r border-neutral-800/70" />
                    <div
                      className="absolute top-1/2 h-4 -translate-y-1/2 rounded-[9999px] shadow-[0_0_18px_rgba(255,255,255,0.08)]"
                      style={{
                        left: `${left}%`,
                        width: `${width}%`,
                        minWidth: 6,
                        backgroundColor: colorForDark(row.model.dev),
                        opacity: row.deprecated ? 0.5 : 0.9,
                      }}
                    />
                  </div>
                </button>
              )
            })}
          </div>

        </div>
      )}
    </div>
  )
}
