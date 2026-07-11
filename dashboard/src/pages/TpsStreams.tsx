import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import ThroughputCoinCanvas from '../components/ThroughputCoinCanvas'
import { loadEnrichment, loadModels, loadThroughput, useData } from '../lib/data'
import { buildThroughputRows, type ThroughputOrder, type ThroughputRow } from '../lib/throughput'
import { colorForDark } from '../lib/theme'

type SourceFilter = 'all' | 'local_omp' | 'artificialanalysis'

const FILTERS: Array<{ label: string; value: SourceFilter }> = [
  { label: 'All', value: 'all' },
  { label: 'Local OMP', value: 'local_omp' },
  { label: 'Artificial Analysis', value: 'artificialanalysis' },
]

const ORDER_FILTERS: Array<{ label: string; value: ThroughputOrder; description: string }> = [
  { label: 'Fastest', value: 'fastest', description: 'highest output TPS first' },
  { label: 'Median band', value: 'medianBand', description: 'representative rows near the median TPS first' },
  { label: 'Slowest', value: 'slowest', description: 'lowest positive TPS first' },
]

const sourceLabel: Record<ThroughputRow['source'], string> = {
  local_omp: 'Local OMP',
  artificialanalysis: 'Artificial Analysis',
}

export default function TpsStreams() {
  const [searchParams, setSearchParams] = useSearchParams()
  const sourceParam = searchParams.get('source')
  const orderParam = searchParams.get('order')
  const lanesParam = searchParams.get('lanes')
  const lanesParamConsumedRef = useRef(searchParams.has('lanes'))
  const userToggledLanesRef = useRef(false)
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const { data: enrichment, loading: enrichmentLoading, error: enrichmentError } = useData(loadEnrichment)
  const { data: throughput, error: throughputError } = useData(loadThroughput)
  const sourceFilter: SourceFilter =
    sourceParam === 'local_omp' || sourceParam === 'artificialanalysis' ? sourceParam : 'all'
  const throughputOrder: ThroughputOrder =
    orderParam === 'slowest' || orderParam === 'medianBand' ? orderParam : 'fastest'
  const [selectedKeys, setSelectedKeys] = useState<string[]>(() =>
    lanesParam ? lanesParam.split(',').filter(Boolean) : [],
  )
  const [hoverKey, setHoverKey] = useState<string | null>(null)

  const throughputMissing = throughputError?.includes('/data/throughput.json: HTTP 404') ?? false
  const throughputWarning = throughputError && !throughputMissing ? throughputError : null
  const filterCounts = useMemo<Record<SourceFilter, number>>(() => {
    if (!models || !enrichment) return { all: 0, local_omp: 0, artificialanalysis: 0 }

    const counts: Record<SourceFilter, number> = { all: 0, local_omp: 0, artificialanalysis: 0 }

    for (const filter of FILTERS) {
      counts[filter.value] = buildThroughputRows(models, enrichment, throughputMissing ? null : (throughput ?? null), {
        maxRows: Number.MAX_SAFE_INTEGER,
        source: filter.value,
      }).length
    }

    return counts
  }, [enrichment, models, throughput, throughputMissing])

  const rows = useMemo(() => {
    if (!models || !enrichment) return []
    return buildThroughputRows(models, enrichment, throughputMissing ? null : (throughput ?? null), {
      maxRows: 40,
      source: sourceFilter,
      order: throughputOrder,
    })
  }, [enrichment, models, sourceFilter, throughput, throughputMissing, throughputOrder])

  useEffect(() => {
    if (lanesParamConsumedRef.current || userToggledLanesRef.current) return

    setSelectedKeys(rows.slice(0, 6).map((row) => row.key))
  }, [rows])

  useEffect(() => {
    const defaultKeys = rows.slice(0, 6).map((row) => row.key)
    const selectedKeysMatchDefault =
      selectedKeys.length === defaultKeys.length && selectedKeys.every((key, index) => key === defaultKeys[index])
    const nextParams = new URLSearchParams(searchParams)

    if (sourceFilter === 'all') {
      nextParams.delete('source')
    } else {
      nextParams.set('source', sourceFilter)
    }

    if (throughputOrder === 'fastest') {
      nextParams.delete('order')
    } else {
      nextParams.set('order', throughputOrder)
    }

    if (selectedKeys.length > 0 && !selectedKeysMatchDefault) {
      nextParams.set('lanes', selectedKeys.join(','))
    } else {
      nextParams.delete('lanes')
    }

    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true })
    }
  }, [rows, searchParams, selectedKeys, setSearchParams, sourceFilter, throughputOrder])

  const selectedRows = rows.filter((row) => selectedKeys.includes(row.key))
  const loading = modelsLoading || enrichmentLoading
  const error = modelsError ?? enrichmentError
  const orderLabel = ORDER_FILTERS.find((filter) => filter.value === throughputOrder)?.label ?? 'Fastest'
  const sourceDescription =
    sourceFilter === 'local_omp'
      ? 'local OMP benchmark runs'
      : sourceFilter === 'artificialanalysis'
        ? 'Artificial Analysis median output TPS'
        : 'local OMP runs plus Artificial Analysis median output TPS'

  if (loading) return <div className="text-neutral-500">Loading throughput streams…</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!models || !enrichment) return null

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-[2rem] border border-amber-400/20 bg-neutral-950 px-6 py-7 shadow-2xl shadow-black/30">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_18%_15%,rgba(245,158,11,0.22),transparent_28%),radial-gradient(circle_at_82%_10%,rgba(217,119,6,0.16),transparent_30%)]" />
        <div className="relative flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.42em] text-amber-300/70">
              Prototype lab
            </div>
            <h1 className="text-4xl font-semibold tracking-tight text-amber-50">Output TPS streams</h1>
            <p className="mt-2 max-w-2xl text-sm text-neutral-400">
              Coin rain scaled by output tokens per second. Showing {orderLabel.toLowerCase()} rows only, not a full
              distribution.
            </p>
          </div>
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-2">
              {FILTERS.map((filter) => (
                <button
                  key={filter.value}
                  className={`rounded-full border px-4 py-2 text-xs font-semibold uppercase tracking-[0.22em] transition ${
                    sourceFilter === filter.value
                      ? 'border-amber-300 bg-amber-300 text-black shadow-lg shadow-amber-500/20'
                      : 'border-amber-300/20 bg-black/30 text-amber-200/70 hover:border-amber-300/50 hover:text-amber-100'
                  }`}
                  type="button"
                  onClick={() => resetRows(filter.value, throughputOrder, sourceFilter, throughputOrder, searchParams, setSearchParams, setSelectedKeys, lanesParamConsumedRef, userToggledLanesRef)}
                >
                  {filter.label} · {filterCounts[filter.value]}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap gap-2">
              {ORDER_FILTERS.map((filter) => (
                <button
                  key={filter.value}
                  className={`rounded-full border px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] transition ${
                    throughputOrder === filter.value
                      ? 'border-neutral-100 bg-neutral-100 text-black'
                      : 'border-neutral-700 bg-black/30 text-neutral-300 hover:border-neutral-400 hover:text-neutral-100'
                  }`}
                  aria-label={filter.label}
                  title={filter.description}
                  type="button"
                  onClick={() => resetRows(sourceFilter, filter.value, sourceFilter, throughputOrder, searchParams, setSearchParams, setSelectedKeys, lanesParamConsumedRef, userToggledLanesRef)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {throughputWarning ? (
        <div className="rounded-2xl border border-amber-400/20 bg-amber-950/20 px-4 py-3 text-sm text-amber-100">
          Local throughput warning: {throughputWarning}
        </div>
      ) : null}

      <div className="rounded-2xl border border-amber-400/20 bg-amber-950/20 px-4 py-3 text-sm text-amber-100">
        Source: {sourceDescription}. Showing {rows.length} {orderLabel.toLowerCase()} positive-TPS rows from{' '}
        {filterCounts[sourceFilter]} available rows. Zero and missing TPS values are excluded.
      </div>

      {rows.length === 0 ? (
        <div className="rounded-[2rem] border border-neutral-800 bg-neutral-900/60 p-8 text-sm text-neutral-400">
          No throughput metrics available. Run dashboard/scripts/extract.mjs or the OMP TPS collector to generate /data/throughput.json.
        </div>
      ) : (
        <section className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
          <div className="max-h-[320px] overflow-y-auto rounded-[2rem] border border-neutral-800 bg-neutral-900/70 p-3 pr-1 xl:max-h-[660px]">
            <div className="px-3 pb-3 pt-2 text-[10px] font-semibold uppercase tracking-[0.28em] text-neutral-500">
              Select lanes
            </div>
            <div className="space-y-2">
              {rows.map((row, index) => {
                const selected = selectedKeys.includes(row.key)
                return (
                  <button
                    key={row.key}
                    className={`w-full rounded-2xl border p-4 text-left transition ${
                      selected
                        ? 'border-amber-300/70 bg-amber-300/10 shadow-lg shadow-amber-950/30'
                        : 'border-neutral-800 bg-black/20 hover:border-neutral-600'
                    } ${hoverKey === row.key ? 'ring-1 ring-amber-300/60' : ''}`}
                    type="button"
                    onClick={() => {
                      userToggledLanesRef.current = true
                      toggleKey(row.key, setSelectedKeys)
                    }}
                    onMouseEnter={() => setHoverKey(row.key)}
                    onMouseLeave={() => setHoverKey(null)}
                  >
                    <div className="flex items-start gap-3">
                      <div
                        className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-bold text-black"
                        style={{ background: colorForDark(row.dev) }}
                      >
                        {index + 1}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-3">
                          <div className="truncate text-sm font-semibold text-neutral-100" title={row.modelName}>
                            {row.modelName}
                          </div>
                          <div className="shrink-0 text-sm font-semibold tabular-nums text-amber-200">
                            {row.tps.toFixed(1)} TPS
                          </div>
                        </div>
                        <div className="mt-1 truncate text-xs text-neutral-500">{row.providerLabel}</div>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-[10px] uppercase tracking-[0.18em]">
                          <span className="rounded-full border border-neutral-700 px-2 py-1 text-neutral-400">
                            {sourceLabel[row.source]}
                          </span>
                          <span className="text-neutral-600">{formatDate(row.measuredAt ?? row.fetchedAt)}</span>
                        </div>
                      </div>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="order-first space-y-3 xl:order-none">
            <ThroughputCoinCanvas rows={selectedRows} highlightKey={hoverKey} onLaneHover={setHoverKey} />
            <div
              className="rounded-2xl border border-neutral-800 bg-neutral-900/70 px-4 py-3 text-xs text-neutral-500"
              title="Coin count = clamp(round(TPS × 1.2), 24, 360). Falling speed uses sqrt(TPS)."
            >
              Each lane rains coins at a rate proportional to the selected model's output speed - denser rain means more
              tokens per second. Gray lane = 100 TPS reference.
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

function resetRows(
  nextSourceFilter: SourceFilter,
  nextThroughputOrder: ThroughputOrder,
  currentSourceFilter: SourceFilter,
  currentThroughputOrder: ThroughputOrder,
  searchParams: URLSearchParams,
  setSearchParams: (nextParams: URLSearchParams, options?: { replace?: boolean }) => void,
  setSelectedKeys: (keys: string[]) => void,
  lanesParamConsumedRef: { current: boolean },
  userToggledLanesRef: { current: boolean },
) {
  if (nextSourceFilter === currentSourceFilter && nextThroughputOrder === currentThroughputOrder) return
  lanesParamConsumedRef.current = false
  userToggledLanesRef.current = false
  setSelectedKeys([])
  const nextParams = new URLSearchParams(searchParams)
  if (nextSourceFilter === 'all') {
    nextParams.delete('source')
  } else {
    nextParams.set('source', nextSourceFilter)
  }
  if (nextThroughputOrder === 'fastest') {
    nextParams.delete('order')
  } else {
    nextParams.set('order', nextThroughputOrder)
  }
  nextParams.delete('lanes')
  setSearchParams(nextParams, { replace: true })
}

function toggleKey(key: string, setSelectedKeys: (updater: (keys: string[]) => string[]) => void) {
  setSelectedKeys((keys) => (keys.includes(key) ? keys.filter((existing) => existing !== key) : [...keys, key]))
}

function formatDate(value: string | null): string {
  if (!value) return 'date unavailable'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}
