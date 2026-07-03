import { useEffect, useMemo, useState } from 'react'
import ThroughputCoinCanvas from '../components/ThroughputCoinCanvas'
import { loadEnrichment, loadModels, loadThroughput, useData } from '../lib/data'
import { buildThroughputRows, type ThroughputRow } from '../lib/throughput'
import { colorForDark } from '../lib/theme'

type SourceFilter = 'all' | 'local_omp' | 'artificialanalysis'

const FILTERS: Array<{ label: string; value: SourceFilter }> = [
  { label: 'All', value: 'all' },
  { label: 'Local OMP', value: 'local_omp' },
  { label: 'Artificial Analysis', value: 'artificialanalysis' },
]

const sourceLabel: Record<ThroughputRow['source'], string> = {
  local_omp: 'Local OMP',
  artificialanalysis: 'Artificial Analysis',
}

export default function TpsStreams() {
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const { data: enrichment, loading: enrichmentLoading, error: enrichmentError } = useData(loadEnrichment)
  const { data: throughput, error: throughputError } = useData(loadThroughput)
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all')
  const [selectedKeys, setSelectedKeys] = useState<string[]>([])

  const throughputMissing = throughputError?.includes('/data/throughput.json: HTTP 404') ?? false
  const throughputWarning = throughputError && !throughputMissing ? throughputError : null
  const rows = useMemo(() => {
    if (!models || !enrichment) return []
    return buildThroughputRows(models, enrichment, throughputMissing ? null : (throughput ?? null), {
      maxRows: 40,
      source: sourceFilter,
    })
  }, [enrichment, models, sourceFilter, throughput, throughputMissing])

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedKeys([])
      return
    }
    setSelectedKeys(rows.slice(0, 6).map((row) => row.key))
  }, [rows, sourceFilter])

  const selectedRows = rows.filter((row) => selectedKeys.includes(row.key))
  const loading = modelsLoading || enrichmentLoading
  const error = modelsError ?? enrichmentError

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
            <h1 className="text-4xl font-semibold tracking-tight text-amber-50">TPS coin streams</h1>
            <p className="mt-2 max-w-2xl text-sm text-neutral-400">
              Gold coin rain scaled by visible output tokens per second.
            </p>
          </div>
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
                onClick={() => setSourceFilter(filter.value)}
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {throughputWarning ? (
        <div className="rounded-2xl border border-amber-400/20 bg-amber-950/20 px-4 py-3 text-sm text-amber-100">
          Local throughput warning: {throughputWarning}
        </div>
      ) : null}

      {rows.length === 0 ? (
        <div className="rounded-[2rem] border border-neutral-800 bg-neutral-900/60 p-8 text-sm text-neutral-400">
          No throughput metrics available. Run dashboard/scripts/extract.mjs or the OMP TPS collector to generate /data/throughput.json.
        </div>
      ) : (
        <section className="grid gap-5 xl:grid-cols-[380px_minmax(0,1fr)]">
          <div className="rounded-[2rem] border border-neutral-800 bg-neutral-900/70 p-3 max-h-[660px] overflow-y-auto pr-1">
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
                    }`}
                    type="button"
                    onClick={() => toggleKey(row.key, setSelectedKeys)}
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
                          <div className="truncate text-sm font-semibold text-neutral-100">{row.modelName}</div>
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

          <div className="space-y-3">
            <ThroughputCoinCanvas rows={selectedRows} />
            <div className="rounded-2xl border border-neutral-800 bg-neutral-900/70 px-4 py-3 text-xs text-neutral-500">
              Coin count = clamp(round(TPS × 1.2), 24, 360). Falling speed uses sqrt(TPS).
            </div>
          </div>
        </section>
      )}
    </div>
  )
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
