import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import LabLogo from '../components/LabLogo'
import { useModelDrawer } from '../components/ModelDrawer'
import { loadAliases, loadElo, loadModels, useData, type Model } from '../lib/data'
import { deltaColorClass, fmtBenchmarkScore, fmtDelta, fmtElo, fmtPrice, fmtTokens } from '../lib/format'

type SortKey =
  | 'name'
  | 'dev'
  | 'released'
  | 'ctx'
  | 'maxOut'
  | 'priceIn'
  | 'priceOut'
  | 'elo'
  | 'swe'
  | 'open'
  | 'delta30d'

const COLUMNS: Array<{ key: SortKey; label: string; numeric?: boolean; help?: string }> = [
  { key: 'name', label: 'Model' },
  { key: 'dev', label: 'Developer' },
  { key: 'released', label: 'Released' },
  { key: 'ctx', label: 'Context', numeric: true, help: 'Context window (tokens)' },
  { key: 'maxOut', label: 'Max out', numeric: true, help: 'Max output tokens' },
  { key: 'priceIn', label: '$ in/1M', numeric: true, help: 'Input price per 1M tokens (USD)' },
  { key: 'priceOut', label: '$ out/1M', numeric: true, help: 'Output price per 1M tokens (USD)' },
  { key: 'elo', label: 'ELO', numeric: true },
  { key: 'delta30d', label: 'Δ30d', numeric: true, help: 'Arena ELO change over the last 30 days' },
  { key: 'swe', label: 'SWE-bench', numeric: true, help: 'SWE-bench Verified score' },
  { key: 'open', label: 'Open' },
]

function sortValue(m: Model, key: SortKey, eloDeltaByModelId: Map<number, number>): string | number | null {
  switch (key) {
    case 'name':
      return m.name.toLowerCase()
    case 'dev':
      return m.dev
    case 'released':
      return m.released
    case 'ctx':
      return m.ctx
    case 'maxOut':
      return m.maxOut
    case 'priceIn':
      return m.priceIn
    case 'priceOut':
      return m.priceOut
    case 'elo':
      return m.scores.lmarena_text_overall?.score ?? null
    case 'delta30d':
      return eloDeltaByModelId.get(m.id) ?? null
    case 'swe':
      return m.scores.swe_bench_verified?.score ?? null
    case 'open':
      return m.open
  }
}

const loadTextOverallElo = () => loadElo('text_overall')

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000

export default function ModelExplorer() {
  const { data: models, loading, error } = useData(loadModels)
  const { data: aliases } = useData(loadAliases)
  const { data: textOverallElo } = useData(loadTextOverallElo)
  const navigate = useNavigate()
  const { openModel } = useModelDrawer()
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState(() => searchParams.get('q') ?? '')
  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const requestedSort = searchParams.get('sort')
    return COLUMNS.some((c) => c.key === requestedSort) ? (requestedSort as SortKey) : 'elo'
  })
  const [sortDesc, setSortDesc] = useState(() => searchParams.get('dir') !== 'asc')

  useEffect(() => {
    const next = new URLSearchParams()
    const trimmedQuery = query.trim()
    if (trimmedQuery) next.set('q', trimmedQuery)
    next.set('sort', sortKey)
    next.set('dir', sortDesc ? 'desc' : 'asc')
    setSearchParams(next, { replace: true })
  }, [query, sortKey, sortDesc, setSearchParams])

  const aliasIndex = useMemo(() => {
    const idx = new Map<number, string>()
    if (!aliases) return idx
    for (const a of aliases) {
      if (a.modelId == null) continue
      idx.set(a.modelId, (idx.get(a.modelId) ?? '') + '\n' + a.alias.toLowerCase())
    }
    return idx
  }, [aliases])

  const eloDeltaByModelId = useMemo(() => {
    const deltas = new Map<number, number>()
    if (!textOverallElo) return deltas
    for (const series of textOverallElo.series) {
      if (series.t.length < 2) continue

      let latestIndex = 0
      for (let i = 1; i < series.t.length; i += 1) {
        if (series.t[i] >= series.t[latestIndex]) latestIndex = i
      }

      const cutoff = series.t[latestIndex] - THIRTY_DAYS_MS
      let priorIndex = -1
      for (let i = 0; i < series.t.length; i += 1) {
        if (i === latestIndex || series.t[i] > cutoff) continue
        if (priorIndex === -1 || series.t[i] > series.t[priorIndex]) priorIndex = i
      }

      if (priorIndex !== -1) {
        deltas.set(series.modelId, series.elo[latestIndex] - series.elo[priorIndex])
      }
    }
    return deltas
  }, [textOverallElo])

  const rows = useMemo(() => {
    if (!models) return []
    const needle = query.trim().toLowerCase()
    let out = models
    if (needle) {
      out = out.filter(
        (m) =>
          m.slug.toLowerCase().includes(needle) ||
          m.name.toLowerCase().includes(needle) ||
          (aliasIndex.get(m.id) ?? '').includes(needle),
      )
    }
    return [...out].sort((a, b) => {
      const av = sortValue(a, sortKey, eloDeltaByModelId)
      const bv = sortValue(b, sortKey, eloDeltaByModelId)
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDesc ? -cmp : cmp
    })
  }, [models, query, sortKey, sortDesc, aliasIndex, eloDeltaByModelId])

  if (loading) return <div className="text-neutral-500">Loading…</div>
  if (error) return <div className="text-red-400">{error}</div>

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search slug, name, or alias…"
          className="w-80 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-200 placeholder-neutral-600 outline-none focus:border-neutral-500"
        />
        <div className="text-xs text-neutral-500">
          {rows.length} of {models?.length ?? 0} models
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="py-16 text-center text-neutral-500">No models match.</div>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-neutral-800">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-neutral-900 text-left text-xs text-neutral-400">
              <tr>
                {COLUMNS.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => {
                      if (sortKey === c.key) setSortDesc((v) => !v)
                      else {
                        setSortKey(c.key)
                        setSortDesc(c.numeric ?? false)
                      }
                    }}
                    title={c.help}
                    className={`cursor-pointer px-3 py-2 font-medium hover:text-neutral-200 ${
                      c.key === 'name' ? 'sticky left-0 z-20 bg-neutral-900' : c.numeric ? 'text-right' : ''
                    }`}
                  >
                    {c.label}
                    {sortKey === c.key ? (sortDesc ? ' ↓' : ' ↑') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr
                  key={m.id}
                  onClick={() => navigate(`/models/${encodeURIComponent(m.slug)}`)}
                  className="group cursor-pointer border-t border-neutral-800/60 hover:bg-neutral-900"
                >
                  <td className="sticky left-0 z-10 bg-neutral-950 px-3 py-2 text-neutral-100 group-hover:bg-neutral-900">
                    <div className="flex max-w-56 items-center gap-2">
                      <span className="block min-w-0 flex-1 truncate" title={m.name}>
                        {m.name}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation()
                          openModel(m.slug)
                        }}
                        className="shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium text-neutral-500 hover:text-neutral-200"
                      >
                        Peek
                      </button>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-neutral-400">
                    {m.dev ? (
                      <Link
                        to={`/devs/${m.dev}`}
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center hover:underline"
                      >
                        <LabLogo dev={m.dev} devName={m.devName} size={20} showLabel labelClassName="truncate" />
                      </Link>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="px-3 py-2 text-neutral-400">{m.released ?? '—'}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{fmtTokens(m.ctx)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{fmtTokens(m.maxOut)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{fmtPrice(m.priceIn)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{fmtPrice(m.priceOut)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">
                    {fmtElo(m.scores.lmarena_text_overall?.score)}
                  </td>
                  <td className={`px-3 py-2 text-right ${deltaColorClass(eloDeltaByModelId.get(m.id))}`}>
                    {fmtDelta(eloDeltaByModelId.get(m.id))}
                  </td>
                  <td className="px-3 py-2 text-right text-neutral-300">
                    {fmtBenchmarkScore(
                      m.scores.swe_bench_verified?.score,
                      m.scores.swe_bench_verified?.metric,
                    )}
                  </td>
                  <td className="px-3 py-2 text-neutral-400">
                    {m.open === 1 ? 'open' : m.open === 0 ? 'closed' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
