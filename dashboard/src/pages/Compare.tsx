import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { loadElo, loadModels, useData, type Model } from '../lib/data'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

const loadOverallElo = () => loadElo('text_overall')

type Side = 'a' | 'b'
type CompareMode = 'higher' | 'lower' | 'later'

interface SpecRow {
  key: string
  label: string
  a: number | string | null
  b: number | string | null
  displayA: string
  displayB: string
  mode?: CompareMode
}

interface SharedScore {
  benchmarkId: string
  label: string
  a: number
  b: number
  aSelfReported: number
  bSelfReported: number
}

const EMPTY_VALUE = 'N/A'

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value == null) return EMPTY_VALUE
  if (value >= 1000) return value.toLocaleString()
  return value.toFixed(digits).replace(/\.00$/, '')
}

function formatScore(value: number | null | undefined) {
  if (value == null) return EMPTY_VALUE
  return String(Math.round(value))
}

function formatPrice(value: number | null | undefined) {
  if (value == null) return EMPTY_VALUE
  return `$${formatNumber(value)}`
}

function formatOpen(value: number | null | undefined) {
  if (value === 1) return 'open'
  if (value === 0) return 'closed'
  return EMPTY_VALUE
}

function compareValues(
  left: number | string | null,
  right: number | string | null,
  mode: CompareMode | undefined,
): 'a' | 'b' | null {
  if (!mode || left == null || right == null || left === right) return null
  const a = mode === 'later' ? Date.parse(String(left)) : Number(left)
  const b = mode === 'later' ? Date.parse(String(right)) : Number(right)
  if (!Number.isFinite(a) || !Number.isFinite(b) || a === b) return null
  if (mode === 'lower') return a < b ? 'a' : 'b'
  return a > b ? 'a' : 'b'
}

function benchmarkLabel(id: string) {
  return id
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .replace(/Gpqa/g, 'GPQA')
    .replace(/Mmlu/g, 'MMLU')
    .replace(/Swe/g, 'SWE')
}

function paramModel(params: URLSearchParams, key: Side, models: Model[] | null) {
  const slug = params.get(key)
  if (!slug || !models) return null
  return models.find((model) => model.slug === slug) ?? null
}

export default function Compare() {
  const { data: models, loading, error } = useData(loadModels)
  const { data: elo } = useData(loadOverallElo)
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState<Record<Side, string>>({ a: '', b: '' })

  const modelA = paramModel(params, 'a', models)
  const modelB = paramModel(params, 'b', models)
  const selectedCount = Number(Boolean(modelA)) + Number(Boolean(modelB))

  const setModel = (side: Side, model: Model) => {
    const next = new URLSearchParams(params)
    next.set(side, model.slug)
    setParams(next)
    setSearch((current) => ({ ...current, [side]: '' }))
  }

  const clearModel = (side: Side) => {
    const next = new URLSearchParams(params)
    next.delete(side)
    setParams(next)
  }

  const sharedScores = useMemo<SharedScore[]>(() => {
    if (!modelA || !modelB) return []
    return Object.entries(modelA.scores)
      .filter(([id, score]) => !id.startsWith('lmarena_') && score && modelB.scores[id])
      .map(([id, score]) => ({
        benchmarkId: id,
        label: benchmarkLabel(id),
        a: score.score,
        b: modelB.scores[id].score,
        aSelfReported: score.selfReported,
        bSelfReported: modelB.scores[id].selfReported,
      }))
      .sort((left, right) => right.a + right.b - (left.a + left.b))
  }, [modelA, modelB])

  const specRows = useMemo<SpecRow[]>(() => {
    if (!modelA || !modelB) return []
    return [
      {
        key: 'released',
        label: 'Released',
        a: modelA.released,
        b: modelB.released,
        displayA: modelA.released ?? EMPTY_VALUE,
        displayB: modelB.released ?? EMPTY_VALUE,
        mode: 'later',
      },
      {
        key: 'cutoff',
        label: 'Knowledge cutoff',
        a: modelA.cutoff,
        b: modelB.cutoff,
        displayA: modelA.cutoff ?? EMPTY_VALUE,
        displayB: modelB.cutoff ?? EMPTY_VALUE,
        mode: 'later',
      },
      {
        key: 'ctx',
        label: 'Context window',
        a: modelA.ctx,
        b: modelB.ctx,
        displayA: modelA.ctx == null ? EMPTY_VALUE : modelA.ctx.toLocaleString(),
        displayB: modelB.ctx == null ? EMPTY_VALUE : modelB.ctx.toLocaleString(),
        mode: 'higher',
      },
      {
        key: 'maxOut',
        label: 'Max output',
        a: modelA.maxOut,
        b: modelB.maxOut,
        displayA: modelA.maxOut == null ? EMPTY_VALUE : modelA.maxOut.toLocaleString(),
        displayB: modelB.maxOut == null ? EMPTY_VALUE : modelB.maxOut.toLocaleString(),
        mode: 'higher',
      },
      {
        key: 'priceIn',
        label: 'Input price / 1M',
        a: modelA.priceIn,
        b: modelB.priceIn,
        displayA: formatPrice(modelA.priceIn),
        displayB: formatPrice(modelB.priceIn),
        mode: 'lower',
      },
      {
        key: 'priceOut',
        label: 'Output price / 1M',
        a: modelA.priceOut,
        b: modelB.priceOut,
        displayA: formatPrice(modelA.priceOut),
        displayB: formatPrice(modelB.priceOut),
        mode: 'lower',
      },
      {
        key: 'open',
        label: 'Open weights',
        a: modelA.open,
        b: modelB.open,
        displayA: formatOpen(modelA.open),
        displayB: formatOpen(modelB.open),
        mode: 'higher',
      },
      {
        key: 'lmarena_text_overall',
        label: 'LMArena text overall',
        a: modelA.scores.lmarena_text_overall?.score ?? null,
        b: modelB.scores.lmarena_text_overall?.score ?? null,
        displayA: formatScore(modelA.scores.lmarena_text_overall?.score),
        displayB: formatScore(modelB.scores.lmarena_text_overall?.score),
        mode: 'higher',
      },
      {
        key: 'lmarena_text_coding',
        label: 'LMArena text coding',
        a: modelA.scores.lmarena_text_coding?.score ?? null,
        b: modelB.scores.lmarena_text_coding?.score ?? null,
        displayA: formatScore(modelA.scores.lmarena_text_coding?.score),
        displayB: formatScore(modelB.scores.lmarena_text_coding?.score),
        mode: 'higher',
      },
    ]
  }, [modelA, modelB])

  const scoreOption = useMemo<EChartsCoreOption | null>(() => {
    if (!modelA || !modelB || sharedScores.length === 0) return null
    const rows = [...sharedScores].reverse()
    return {
      backgroundColor: 'transparent',
      grid: { left: 132, right: 32, top: 24, bottom: 36 },
      xAxis: {
        type: 'value',
        axisLabel: { color: '#a3a3a3' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      yAxis: {
        type: 'category',
        data: rows.map((row) => row.label),
        axisLabel: { color: '#d4d4d4', fontSize: 11 },
      },
      legend: { top: 0, textStyle: { color: '#a3a3a3' } },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        valueFormatter: (value: number) => formatNumber(value),
      },
      series: [
        {
          name: modelA.name,
          type: 'bar',
          data: rows.map((row) => ({
            value: row.a,
            itemStyle: {
              color: colorForDark(modelA.dev),
              opacity: row.aSelfReported === 1 ? 0.45 : 0.9,
              borderColor: row.aSelfReported === 1 ? '#fbbf24' : undefined,
              borderWidth: row.aSelfReported === 1 ? 1 : 0,
            },
          })),
          barMaxWidth: 14,
        },
        {
          name: modelB.name,
          type: 'bar',
          data: rows.map((row) => ({
            value: row.b,
            itemStyle: {
              color: colorForDark(modelB.dev),
              opacity: row.bSelfReported === 1 ? 0.45 : 0.9,
              borderColor: row.bSelfReported === 1 ? '#fbbf24' : undefined,
              borderWidth: row.bSelfReported === 1 ? 1 : 0,
            },
          })),
          barMaxWidth: 14,
        },
      ],
    }
  }, [modelA, modelB, sharedScores])

  const eloOption = useMemo<EChartsCoreOption | null>(() => {
    if (!elo || !modelA || !modelB) return null
    const wanted = new Map([
      [modelA.id, modelA],
      [modelB.id, modelB],
    ])
    const series = elo.series
      .filter((entry) => wanted.has(entry.modelId) && entry.t.length > 0)
      .map((entry) => {
        const model = wanted.get(entry.modelId)!
        return {
          name: model.name,
          type: 'line' as const,
          showSymbol: false,
          sampling: 'lttb' as const,
          data: entry.t.map((t, index) => [t, entry.elo[index]]),
          lineStyle: { width: 2, color: colorForDark(model.dev) },
          itemStyle: { color: colorForDark(model.dev) },
          emphasis: { focus: 'series' as const },
        }
      })
    if (series.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 24, top: 32, bottom: 76 },
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
      legend: { top: 0, textStyle: { color: '#a3a3a3' } },
      tooltip: {
        trigger: 'axis',
        order: 'valueDesc',
        confine: true,
        valueFormatter: (value: number) => String(Math.round(value)),
      },
      series,
    }
  }, [elo, modelA, modelB])

  const scoreRef = useECharts(scoreOption)
  const eloRef = useECharts(eloOption)

  if (loading) return <div className="text-neutral-500">Loading...</div>
  if (error) return <div className="text-red-400">{error}</div>
  if (!models) return null

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-neutral-100">Compare models</h1>
        <p className="mt-1 text-xs text-neutral-500">
          Pick two models to compare specs, shared benchmark scores, and Arena history.
        </p>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <ModelPicker
          label="Model A"
          side="a"
          model={modelA}
          models={models}
          query={search.a}
          onQuery={(query) => setSearch((current) => ({ ...current, a: query }))}
          onSelect={setModel}
          onClear={clearModel}
        />
        <ModelPicker
          label="Model B"
          side="b"
          model={modelB}
          models={models}
          query={search.b}
          onQuery={(query) => setSearch((current) => ({ ...current, b: query }))}
          onSelect={setModel}
          onClear={clearModel}
        />
      </div>

      {selectedCount < 2 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-6 text-sm text-neutral-400">
          Select {selectedCount === 0 ? 'two models' : 'one more model'} to unlock the head-to-head
          table and charts. Query params like <span className="text-neutral-200">?a=slug&b=slug</span>{' '}
          are supported.
        </div>
      ) : modelA && modelB ? (
        <>
          <div className="overflow-x-auto rounded-lg border border-neutral-800 bg-neutral-900 p-4">
            <h2 className="mb-3 text-sm font-semibold text-neutral-200">Head-to-head specs</h2>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-neutral-500">
                <tr>
                  <th className="px-3 py-2 font-medium">Metric</th>
                  <th className="px-3 py-2 font-medium">{modelA.name}</th>
                  <th className="px-3 py-2 font-medium">{modelB.name}</th>
                </tr>
              </thead>
              <tbody>
                {specRows.map((row) => {
                  const winner = compareValues(row.a, row.b, row.mode)
                  return (
                    <tr key={row.key} className="border-t border-neutral-800/70">
                      <td className="px-3 py-2 text-neutral-500">{row.label}</td>
                      <td
                        className={`px-3 py-2 ${
                          winner === 'a' ? 'text-emerald-400' : 'text-neutral-300'
                        }`}
                      >
                        {row.displayA}
                      </td>
                      <td
                        className={`px-3 py-2 ${
                          winner === 'b' ? 'text-emerald-400' : 'text-neutral-300'
                        }`}
                      >
                        {row.displayB}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="grid gap-5 xl:grid-cols-2">
            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <h2 className="mb-1 text-sm font-semibold text-neutral-200">Shared benchmarks</h2>
              <p className="mb-2 text-xs text-neutral-500">
                LMArena series are shown in the spec table. Amber badges indicate self-reported
                scores.
              </p>
              {scoreOption ? (
                <div ref={scoreRef} className="h-[420px] w-full" />
              ) : (
                <div className="py-16 text-center text-sm text-neutral-500">
                  No shared non-LMArena benchmark scores.
                </div>
              )}
              {sharedScores.length > 0 && (
                <div className="mt-4 grid gap-2 text-xs text-neutral-400">
                  {sharedScores.map((score) => (
                    <div
                      key={score.benchmarkId}
                      className="grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 rounded-md border border-neutral-800/70 px-3 py-2"
                    >
                      <div className="text-neutral-300">{score.label}</div>
                      <ScoreCell value={score.a} selfReported={score.aSelfReported} />
                      <ScoreCell value={score.b} selfReported={score.bSelfReported} />
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              <h2 className="mb-1 text-sm font-semibold text-neutral-200">Text overall ELO history</h2>
              <p className="mb-2 text-xs text-neutral-500">
                Lines use the developer brand colors from the rest of the dashboard.
              </p>
              {eloOption ? (
                <div ref={eloRef} className="h-[420px] w-full" />
              ) : (
                <div className="py-16 text-center text-sm text-neutral-500">
                  No text overall ELO history for the selected models.
                </div>
              )}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}

function ModelPicker({
  label,
  side,
  model,
  models,
  query,
  onQuery,
  onSelect,
  onClear,
}: {
  label: string
  side: Side
  model: Model | null
  models: Model[]
  query: string
  onQuery: (query: string) => void
  onSelect: (side: Side, model: Model) => void
  onClear: (side: Side) => void
}) {
  const results = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return []
    return models
      .filter(
        (candidate) =>
          candidate.slug.toLowerCase().includes(needle) ||
          candidate.name.toLowerCase().includes(needle),
      )
      .slice(0, 12)
  }, [models, query])

  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wide text-neutral-600">{label}</div>
          <div className="mt-1 flex items-center gap-2 text-sm font-medium text-neutral-100">
            {model && (
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ backgroundColor: colorForDark(model.dev) }}
              />
            )}
            {model?.name ?? 'No model selected'}
          </div>
        </div>
        {model && (
          <button
            onClick={() => onClear(side)}
            className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-400 hover:border-neutral-500 hover:text-neutral-200"
          >
            Clear
          </button>
        )}
      </div>
      <div className="relative">
        <input
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Search slug or name..."
          className="w-full rounded-md border border-neutral-700 bg-neutral-950 px-3 py-2 text-sm text-neutral-200 placeholder-neutral-600 outline-none focus:border-neutral-500"
        />
        {results.length > 0 && (
          <div className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-neutral-700 bg-neutral-900 shadow-xl">
            {results.map((candidate) => (
              <button
                key={candidate.id}
                onClick={() => onSelect(side, candidate)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs text-neutral-300 hover:bg-neutral-800"
              >
                <span className="min-w-0">
                  <span className="block truncate text-neutral-200">{candidate.name}</span>
                  <span className="block truncate text-neutral-600">{candidate.slug}</span>
                </span>
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ backgroundColor: colorForDark(candidate.dev) }}
                />
              </button>
            ))}
          </div>
        )}
        {query.trim() && results.length === 0 && (
          <div className="absolute z-20 mt-1 w-full rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-xs text-neutral-500 shadow-xl">
            No models match.
          </div>
        )}
      </div>
      {model && <div className="mt-2 truncate text-xs text-neutral-600">{model.slug}</div>}
    </div>
  )
}

function ScoreCell({ value, selfReported }: { value: number; selfReported: number }) {
  return (
    <div className="flex items-center gap-1.5 text-right tabular-nums text-neutral-300">
      <span>{formatNumber(value)}</span>
      {selfReported === 1 && (
        <span className="rounded border border-amber-500/50 bg-amber-950/50 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-amber-300">
          self
        </span>
      )}
    </div>
  )
}
