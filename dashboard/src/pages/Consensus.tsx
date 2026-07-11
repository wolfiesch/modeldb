import { useMemo, useState } from 'react'
import { loadBenchmarks, loadModels, useData } from '../lib/data'
import {
  buildConsensusRows,
  DEFAULT_CONSENSUS_BENCHMARKS,
  type ConsensusRow,
} from '../lib/consensus'
import DevFilter from '../components/DevFilter'
import {
  fmtScore,
  fmtPercent,
  confidenceTier,
  CONFIDENCE_LABEL,
  CONFIDENCE_CLASS,
  disagreementTier,
  DISAGREEMENT_LABEL,
  DISAGREEMENT_CLASS,
} from '../lib/format'

const MATRIX_BENCHMARKS = DEFAULT_CONSENSUS_BENCHMARKS

export default function Consensus() {
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const { data: benchmarks, loading: benchLoading, error: benchError } = useData(loadBenchmarks)

  const [minScored, setMinScored] = useState<number>(3)
  const [openOnly, setOpenOnly] = useState<boolean>(false)
  const [devFilter, setDevFilter] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<'consensus' | 'disagreement' | 'count'>('consensus')

  const matrix = useMemo<ConsensusRow[]>(() => {
    if (!models || !benchmarks) return []
    return buildConsensusRows(models, benchmarks, MATRIX_BENCHMARKS)
  }, [models, benchmarks])

  // Filtered and sorted rows
  const displayRows = useMemo(() => {
    return matrix
      .filter((row) => row.benchmarkCount >= minScored)
      .filter((row) => (openOnly ? row.openWeights : true))
      .filter((row) => (devFilter ? row.developer === devFilter : true))
      .sort((a, b) => {
        if (sortBy === 'disagreement') {
          return b.disagreementScore - a.disagreementScore
        }
        if (sortBy === 'count') {
          return b.benchmarkCount - a.benchmarkCount
        }
        return b.consensusScore - a.consensusScore
      })
  }, [matrix, minScored, openOnly, devFilter, sortBy])

  const devs = useMemo(() => {
    if (!models) return []
    const seen = new Set<string>()
    for (const m of models) {
      if (m.dev) seen.add(m.dev)
    }
    return [...seen].sort()
  }, [models])

  if (modelsLoading || benchLoading) return <div className="text-neutral-500">Loading…</div>
  if (modelsError || benchError) return <div className="text-red-400">{modelsError ?? benchError}</div>
  if (!models || !benchmarks) return null

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-neutral-100">Consensus & Disagreement Matrix</h1>
        <p className="mt-1 text-xs text-neutral-500">
          Analyze models across {MATRIX_BENCHMARKS.length} signals, including Arena perception and independent benchmarks. Scores are converted to percentiles within each signal.
          Consensus is a reliability-weighted percentile average; Disagreement remains the raw standard deviation diagnostic.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-neutral-500" htmlFor="min-benchmarks">Min Benchmarks</label>
          <select
            id="min-benchmarks"
            value={minScored}
            onChange={(e) => setMinScored(Number(e.target.value))}
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
          >
            {[1, 2, 3, 5, 8].map((n) => (
              <option key={n} value={n}>
                At least {n} scored
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase tracking-wider text-neutral-500" htmlFor="sort-by">Sort By</label>
          <select
            id="sort-by"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as 'consensus' | 'disagreement' | 'count')}
            className="rounded border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200"
          >
            <option value="consensus">Consensus (Avg Percentile)</option>
            <option value="disagreement">Disagreement (Std Dev)</option>
            <option value="count">Count of Benchmarks</option>
          </select>
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

      <div className="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900">
        <table className="w-full border-collapse text-left text-xs">
          <thead>
            <tr className="border-b border-neutral-800 bg-neutral-950 text-neutral-400">
              <th className="sticky left-0 bg-neutral-950 px-4 py-3 font-medium min-w-48">Model</th>
              <th className="px-3 py-3 font-medium text-center">Scored</th>
              <th className="px-3 py-3 font-medium text-right">Consensus</th>
              <th className="px-3 py-3 font-medium text-right">Disagreement</th>
              {MATRIX_BENCHMARKS.map((col) => (
                <th key={col.id} className="px-2 py-3 font-medium text-center min-w-24">
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-neutral-800/50">
            {displayRows.map((row) => (
              <tr key={row.modelId} className="hover:bg-neutral-800/20">
                <td className="sticky left-0 bg-neutral-900/90 font-medium text-neutral-200 px-4 py-3 flex items-center gap-2">
                  <span className="truncate max-w-40" title={row.modelName}>{row.modelName}</span>
                  {row.openWeights && (
                    <span className="rounded bg-emerald-950 text-[10px] text-emerald-400 px-1 border border-emerald-800">
                      OSS
                    </span>
                  )}
                </td>
                <td className="px-3 py-3 text-center">
                  <span
                    className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${CONFIDENCE_CLASS[confidenceTier(row.benchmarkCount)]}`}
                    title={CONFIDENCE_LABEL[confidenceTier(row.benchmarkCount)]}
                  >
                    {row.benchmarkCount}
                  </span>
                </td>
                <td className="px-3 py-3 text-right font-semibold text-cyan-400">
                  {fmtPercent(row.consensusScore)}
                </td>
                <td className={`px-3 py-3 text-right ${DISAGREEMENT_CLASS[disagreementTier(row.disagreementScore)]}`}>
                  {row.disagreementScore.toFixed(1)}
                  <span className="ml-1 text-[10px] text-neutral-500">
                    {DISAGREEMENT_LABEL[disagreementTier(row.disagreementScore)]}
                  </span>
                </td>
                {MATRIX_BENCHMARKS.map((col) => {
                  const cell = row.scores[col.id]
                  if (!cell) {
                    return (
                      <td key={col.id} className="px-2 py-3 text-center text-neutral-700 bg-neutral-950/20">
                        —
                      </td>
                    )
                  }

                  const p = cell.percentile
                  const bg =
                    p >= 85
                      ? 'bg-emerald-950/80 text-emerald-300 border-emerald-900/50'
                      : p >= 65
                        ? 'bg-teal-950/60 text-teal-300 border-teal-900/30'
                        : p >= 40
                          ? 'bg-amber-950/50 text-amber-300 border-amber-900/30'
                          : 'bg-red-950/50 text-red-300 border-red-900/30'

                  return (
                    <td
                      key={col.id}
                      className={`px-2 py-3 text-center border-t border-neutral-900 ${bg}`}
                      title={`${row.modelName} on ${col.label}\nScore: ${cell.score} (${cell.percentile.toFixed(0)}th percentile)\nRank: ${cell.rank}/${cell.total}`}
                    >
                      <div className="font-semibold">{cell.percentile.toFixed(0)}%</div>
                      <div className="text-[10px] opacity-75">{fmtScore(cell.score)}</div>
                    </td>
                  )
                })}
              </tr>
            ))}
            {displayRows.length === 0 && (
              <tr>
                <td colSpan={MATRIX_BENCHMARKS.length + 4} className="py-8 text-center text-neutral-500">
                  No models match the filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
