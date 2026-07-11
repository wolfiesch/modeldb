import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import LabLogo from '../components/LabLogo'
import { useModelDrawer } from '../components/ModelDrawer'
import { loadBenchmarks, loadElo, loadMeta, loadModels, useData, type Benchmark, type BenchmarkResult, type Model } from '../lib/data'
import { CONFIDENCE_CLASS, CONFIDENCE_LABEL, confidenceTier, fmtCount, fmtDelta, fmtElo, fmtPercent, fmtPrice } from '../lib/format'
import { colorForDark, shortName } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

const loadTextOverallElo = () => loadElo('text_overall')

const monthFormatter = new Intl.DateTimeFormat('en', { month: 'short', year: 'numeric', timeZone: 'UTC' })

function monthStart(value: number) {
  const date = new Date(value)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), 1)
}

function nextMonthStart(value: number) {
  const date = new Date(value)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 1)
}

function lastIndexAtOrBefore(values: number[], cutoff: number) {
  let lo = 0
  let hi = values.length - 1
  let found = -1
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2)
    if (values[mid] <= cutoff) {
      found = mid
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return found
}

interface FrontierPoint {
  slug: string
  name: string
  dev: string | null
  price: number
  elo: number
  open: number | null
  isFrontier: boolean
}

function formatBenchmarkScore(score: number, metric: string | null | undefined) {
  const metricText = (metric ?? '').toLowerCase()
  const isPercentLike =
    metricText.includes('percent') ||
    metricText.includes('resolved') ||
    metricText.includes('pass') ||
    metricText.includes('accuracy')

  if (score > 0 && score <= 1 && isPercentLike) return `${(score * 100).toFixed(1)}%`
  if (Number.isInteger(score)) return score.toLocaleString()
  return score.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

const LEAGUE_CATEGORIES = [
  { key: 'arena', label: 'Arena (ELO)' },
  { key: 'coding', label: 'Coding' },
  { key: 'math', label: 'Math' },
  { key: 'reasoning', label: 'Reasoning' },
  { key: 'agentic', label: 'Agentic' },
  { key: 'knowledge', label: 'Knowledge' },
] as const

type LeagueCategoryKey = (typeof LEAGUE_CATEGORIES)[number]['key']
type LeagueSortKey = 'consensus' | LeagueCategoryKey

interface LeagueCell {
  percentile: number
  benchmarkCount: number
}

interface LeagueRow {
  modelId: number
  slug: string
  name: string
  dev: string | null
  devName: string | null
  open: number | null
  consensus: number
  categoryScores: Partial<Record<LeagueCategoryKey, LeagueCell>>
  scoredSignalCount: number
}

function latestBestResultsForBenchmark(benchmark: Benchmark) {
  const results = benchmark.results ?? []
  if (results.length === 0) return new Map<number, BenchmarkResult>()

  let latestFetchedTime = -Infinity
  let latestSnapshotId: number | null = null
  for (const result of results) {
    const fetchedTime = result.fetchedAt ? Date.parse(result.fetchedAt) : 0
    if (fetchedTime > latestFetchedTime) {
      latestFetchedTime = fetchedTime
      latestSnapshotId = result.sourceSnapshotId ?? null
    } else if (
      fetchedTime === latestFetchedTime &&
      result.sourceSnapshotId != null &&
      (latestSnapshotId == null || result.sourceSnapshotId > latestSnapshotId)
    ) {
      latestSnapshotId = result.sourceSnapshotId
    }
  }

  const higherIsBetter = benchmark.higherIsBetter !== 0
  const bestByModel = new Map<number, BenchmarkResult>()
  for (const result of results) {
    const fetchedTime = result.fetchedAt ? Date.parse(result.fetchedAt) : 0
    if (fetchedTime !== latestFetchedTime) continue
    if (latestSnapshotId != null && result.sourceSnapshotId !== latestSnapshotId) {
      continue
    }

    const existing = bestByModel.get(result.modelId)
    if (!existing || (higherIsBetter ? result.score > existing.score : result.score < existing.score)) {
      bestByModel.set(result.modelId, result)
    }
  }
  return bestByModel
}

function percentileByModel<T>(
  entries: Array<{ modelId: number; value: number; source: T }>,
  higherIsBetter: boolean,
) {
  const sorted = [...entries].sort((a, b) => (higherIsBetter ? b.value - a.value : a.value - b.value))
  const total = sorted.length
  const percentiles = new Map<number, { percentile: number; source: T }>()
  sorted.forEach((entry, index) => {
    percentiles.set(entry.modelId, {
      percentile: total > 1 ? (1 - index / (total - 1)) * 100 : 100,
      source: entry.source,
    })
  })
  return percentiles
}

export default function Overview() {
  const { data: meta } = useData(loadMeta)
  const { data: models, loading, error } = useData(loadModels)
  const { data: eloHistory, loading: eloLoading, error: eloError } = useData(loadTextOverallElo)
  const { data: benchmarks } = useData(loadBenchmarks)
  const navigate = useNavigate()
  const { openModel } = useModelDrawer()
  const [devFilter, setDevFilter] = useState<string | null>(null)
  const [openOnly, setOpenOnly] = useState(false)
  const [showPareto, setShowPareto] = useState(true)
  const [scrubIndex, setScrubIndex] = useState<number | null>(null)
  const [playing, setPlaying] = useState(false)
  const [leagueSortBy, setLeagueSortBy] = useState<LeagueSortKey>('consensus')
  const [leagueLimit, setLeagueLimit] = useState<10 | 30>(10)
  const modelById = useMemo(() => new Map((models ?? []).map((m) => [m.id, m])), [models])

  const months = useMemo(() => {
    if (!eloHistory) return []
    const seen = new Set<number>()
    for (const series of eloHistory.series) {
      for (const t of series.t) seen.add(monthStart(t))
    }
    return [...seen].sort((a, b) => a - b)
  }, [eloHistory])

  useEffect(() => {
    if (months.length === 0) return
    setScrubIndex((current) => {
      if (current == null) return months.length - 1
      return Math.min(current, months.length - 1)
    })
  }, [months])

  useEffect(() => {
    if (!playing || months.length === 0) return
    const timer = window.setInterval(() => {
      setScrubIndex((current) => {
        const next = current == null ? 0 : current + 1
        if (next >= months.length) {
          window.clearInterval(timer)
          setPlaying(false)
          return months.length - 1
        }
        return next
      })
    }, 250)
    return () => window.clearInterval(timer)
  }, [playing, months])

  const selectedMonth =
    scrubIndex == null ? (months.at(-1) ?? null) : (months[Math.min(scrubIndex, months.length - 1)] ?? null)
  const latestMonth = months.at(-1) ?? null
  const isHistorical = selectedMonth != null && latestMonth != null && selectedMonth < latestMonth
  const selectedMonthLabel = selectedMonth == null ? 'Latest' : monthFormatter.format(selectedMonth)

  const eloByModel = useMemo(() => {
    if (!eloHistory || selectedMonth == null) return new Map<number, number>()
    const cutoff = nextMonthStart(selectedMonth) - 1
    const readings = new Map<number, number>()
    for (const series of eloHistory.series) {
      const index = lastIndexAtOrBefore(series.t, cutoff)
      if (index >= 0) readings.set(series.modelId, series.elo[index])
    }
    return readings
  }, [eloHistory, selectedMonth])

  const points = useMemo<FrontierPoint[]>(() => {
    if (!models || selectedMonth == null) return []
    const basePoints = models
      .filter(
        (m): m is Model & { priceOut: number } =>
          m.priceOut != null && m.priceOut > 0 && eloByModel.has(m.id),
      )
      .filter((m) => (devFilter ? m.dev === devFilter : true))
      .filter((m) => (openOnly ? m.open === 1 : true))
      .map((m) => ({
        slug: m.slug,
        name: m.name,
        dev: m.dev,
        price: m.priceOut,
        elo: eloByModel.get(m.id) ?? 0,
        open: m.open,
        isFrontier: false,
      }))

    const ordered = [...basePoints].sort((a, b) => a.price - b.price || b.elo - a.elo)
    let bestElo = -Infinity
    const frontier = new Set<FrontierPoint>()
    for (const point of ordered) {
      if (point.elo > bestElo) {
        frontier.add(point)
        bestElo = point.elo
      }
    }
    return basePoints.map((point) => ({ ...point, isFrontier: frontier.has(point) }))
  }, [models, selectedMonth, eloByModel, devFilter, openOnly])

  const frontierPoints = useMemo(
    () =>
      points
        .filter((point) => point.isFrontier)
        .sort((a, b) => a.price - b.price || a.elo - b.elo),
    [points],
  )

  const devs = useMemo(() => {
    if (!models) return []
    const seen = new Set<string>()
    for (const m of models) {
      if (m.dev && m.priceOut != null && m.scores.lmarena_text_overall != null) seen.add(m.dev)
    }
    return [...seen].sort()
  }, [models])

  const leagueRows = useMemo<LeagueRow[]>(() => {
    if (!models || !benchmarks || !eloHistory) return []

    const categoryTotals = new Map<number, Partial<Record<LeagueCategoryKey, { sum: number; count: number }>>>()
    const addCategoryScore = (modelId: number, category: LeagueCategoryKey, percentile: number) => {
      const totals = categoryTotals.get(modelId) ?? {}
      const categoryTotal = totals[category] ?? { sum: 0, count: 0 }
      totals[category] = { sum: categoryTotal.sum + percentile, count: categoryTotal.count + 1 }
      categoryTotals.set(modelId, totals)
    }

    const latestEloEntries = eloHistory.series
      .map((series) => {
        const latestElo = series.elo.at(-1)
        return latestElo == null ? null : { modelId: series.modelId, value: latestElo, source: latestElo }
      })
      .filter((entry): entry is { modelId: number; value: number; source: number } => entry != null)
    for (const [modelId, entry] of percentileByModel(latestEloEntries, true)) {
      addCategoryScore(modelId, 'arena', entry.percentile)
    }

    for (const benchmark of benchmarks) {
      if (
        benchmark.category !== 'coding' &&
        benchmark.category !== 'math' &&
        benchmark.category !== 'reasoning' &&
        benchmark.category !== 'agentic' &&
        benchmark.category !== 'knowledge'
      ) {
        continue
      }

      const latestBestResults = latestBestResultsForBenchmark(benchmark)
      if (latestBestResults.size === 0) continue

      const entries = [...latestBestResults.entries()].map(([modelId, result]) => ({
        modelId,
        value: result.score,
        source: result,
      }))
      const percentiles = percentileByModel(entries, benchmark.higherIsBetter !== 0)
      for (const [modelId, entry] of percentiles) {
        addCategoryScore(modelId, benchmark.category, entry.percentile)
      }
    }

    return models
      .map((model) => {
        const totals = categoryTotals.get(model.id)
        if (!totals) return null

        const categoryScores: Partial<Record<LeagueCategoryKey, LeagueCell>> = {}
        const blendedPercentiles: number[] = []
        for (const category of LEAGUE_CATEGORIES) {
          const total = totals[category.key]
          if (!total || total.count === 0) continue

          const percentile = total.sum / total.count
          categoryScores[category.key] = { percentile, benchmarkCount: total.count }
          blendedPercentiles.push(percentile)
        }
        if (blendedPercentiles.length === 0) return null

        const scoredSignalCount = Object.values(categoryScores).reduce(
          (sum, cell) => sum + (cell?.benchmarkCount ?? 0),
          0,
        )

        return {
          modelId: model.id,
          slug: model.slug,
          name: model.name,
          dev: model.dev,
          devName: model.devName,
          open: model.open,
          consensus: blendedPercentiles.reduce((sum, value) => sum + value, 0) / blendedPercentiles.length,
          categoryScores,
          scoredSignalCount,
        }
      })
      .filter((row): row is LeagueRow => row != null)
  }, [models, benchmarks, eloHistory])

  const displayedLeagueRows = useMemo(
    () =>
      [...leagueRows]
        .sort((a, b) => {
          const aValue = leagueSortBy === 'consensus' ? a.consensus : (a.categoryScores[leagueSortBy]?.percentile ?? -1)
          const bValue = leagueSortBy === 'consensus' ? b.consensus : (b.categoryScores[leagueSortBy]?.percentile ?? -1)
          return bValue - aValue || a.name.localeCompare(b.name)
        })
        .slice(0, leagueLimit),
    [leagueRows, leagueSortBy, leagueLimit],
  )

  const overviewInsights = useMemo(() => {
    const insights: Array<{ key: string; label: string; value: string; detail: string; slug: string }> = []
    const modelByLeagueId = new Map((models ?? []).map((model) => [model.id, model]))
    const sortedRows = [...leagueRows].sort((a, b) => b.consensus - a.consensus || a.name.localeCompare(b.name))
    const frontierLeader = sortedRows[0]
    if (frontierLeader) {
      insights.push({
        key: 'frontier-leader',
        label: 'Frontier leader',
        value: frontierLeader.name,
        detail: fmtPercent(frontierLeader.consensus),
        slug: frontierLeader.slug,
      })
    }

    if (models && eloHistory) {
      const pricedEloModels = models
        .map((model) => {
          const series = eloHistory.series.find((entry) => entry.modelId === model.id)
          const latestElo = series?.elo.at(-1)
          return model.priceOut != null && model.priceOut > 0 && model.scores.lmarena_text_overall != null && latestElo != null
            ? { model, price: model.priceOut, elo: latestElo }
            : null
        })
        .filter((entry): entry is { model: Model; price: number; elo: number } => entry != null)
        .sort((a, b) => a.price - b.price || b.elo - a.elo)
      const cheapestQuartile = pricedEloModels.slice(0, Math.max(1, Math.ceil(pricedEloModels.length / 4)))
      const bestValue = cheapestQuartile.sort((a, b) => b.elo - a.elo || a.price - b.price)[0]
      if (bestValue) {
        insights.push({
          key: 'best-value',
          label: 'Best value',
          value: bestValue.model.name,
          detail: `${fmtPrice(bestValue.price)} out · ${fmtElo(bestValue.elo)}`,
          slug: bestValue.model.slug,
        })
      }
    }

    const bestOpen = sortedRows.find((row) => row.open === 1)
    if (bestOpen) {
      insights.push({
        key: 'best-open',
        label: 'Best open model',
        value: bestOpen.name,
        detail: fmtPercent(bestOpen.consensus),
        slug: bestOpen.slug,
      })
    }

    if (models && eloHistory) {
      let biggestMover: { model: Model; delta: number } | null = null
      for (const series of eloHistory.series) {
        const latestTime = series.t.at(-1)
        const latestElo = series.elo.at(-1)
        if (latestTime == null || latestElo == null) continue
        const previousIndex = lastIndexAtOrBefore(series.t, latestTime - 30 * 24 * 60 * 60 * 1000)
        if (previousIndex < 0) continue
        const delta = latestElo - series.elo[previousIndex]
        const model = modelByLeagueId.get(series.modelId)
        if (!model || delta <= 0) continue
        if (!biggestMover || delta > biggestMover.delta) biggestMover = { model, delta }
      }
      if (biggestMover) {
        insights.push({
          key: 'biggest-mover',
          label: 'Biggest mover',
          value: biggestMover.model.name,
          detail: fmtDelta(biggestMover.delta),
          slug: biggestMover.model.slug,
        })
      }
    }

    return insights
  }, [models, eloHistory, leagueRows])

  const bestCategoryRows = useMemo(
    () =>
      LEAGUE_CATEGORIES.map((category) => {
        const row = leagueRows
          .filter((entry) => entry.categoryScores[category.key])
          .sort(
            (a, b) =>
              (b.categoryScores[category.key]?.percentile ?? -1) -
                (a.categoryScores[category.key]?.percentile ?? -1) || a.name.localeCompare(b.name),
          )[0]

        return row ? { category, row, cell: row.categoryScores[category.key] } : null
      }).filter(
        (entry): entry is {
          category: (typeof LEAGUE_CATEGORIES)[number]
          row: LeagueRow
          cell: LeagueCell
        } => entry != null && entry.cell != null,
      ),
    [leagueRows],
  )

  const option = useMemo<EChartsCoreOption | null>(() => {
    if (points.length === 0) return null
    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left: 60, right: 24, top: 24, bottom: 48 },
      xAxis: {
        type: 'log',
        name: 'Output $/1M tokens (log)',
        nameLocation: 'middle',
        nameGap: 32,
        axisLabel: { color: '#a3a3a3' },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      yAxis: {
        type: 'value',
        name: 'LMArena ELO',
        scale: true,
        axisLabel: { color: '#a3a3a3' },
        nameTextStyle: { color: '#737373' },
        splitLine: { lineStyle: { color: '#262626' } },
      },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data?: { meta?: FrontierPoint } }) => {
          const d = p.data?.meta
          if (!d) return ''
          return `<b>${d.name}</b><br/>$${d.price}/1M out · ELO ${Math.round(d.elo)}${
            d.open === 1 ? '<br/>open weights' : ''
          }`
        },
      },
      series: [
        ...(showPareto && frontierPoints.length > 1
          ? [
              {
                type: 'line',
                step: 'end',
                symbol: 'none',
                silent: true,
                z: 1,
                lineStyle: { color: '#e0245e', width: 1.5, type: 'dashed' },
                data: frontierPoints.map((point) => [point.price, point.elo]),
              },
            ]
          : []),
        {
          type: 'scatter',
          animation: false,
          z: 2,
          symbolSize: 12,
          data: points.map((p) => ({
            value: [p.price, p.elo],
            meta: p,
            symbol: p.open === 1 ? 'diamond' : 'circle',
            itemStyle: {
              color: colorForDark(p.dev),
              opacity: showPareto ? (p.isFrontier ? 0.95 : 0.35) : 0.85,
              borderColor: showPareto && p.isFrontier ? '#f5f5f5' : 'transparent',
              borderWidth: showPareto && p.isFrontier ? 1 : 0,
            },
          })),
        },
      ],
    }
  }, [points, showPareto, frontierPoints])

  const chartRef = useECharts(option, (params) => {
    const p = params as { data?: { meta?: FrontierPoint } }
    if (p.data?.meta) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  })

  const deepsweSignal = useMemo(() => {
    if (!benchmarks || !models) return null
    const deepswe = benchmarks.find((benchmark) => benchmark.id === 'deepswe')
    if (!deepswe?.results?.length) return null

    let topResult: BenchmarkResult | null = null
    for (const result of deepswe.results) {
      if (typeof result.modelId !== 'number' || !modelById.has(result.modelId)) continue
      if (!topResult || result.score > topResult.score) topResult = result
    }

    if (!topResult) return null
    const topModel = modelById.get(topResult.modelId)
    if (!topModel) return null

    return {
      score: formatBenchmarkScore(topResult.score, topResult.metric ?? deepswe.metricDefault),
      modelName: topModel.name,
      modelSlug: topModel.slug,
    }
  }, [benchmarks, models, modelById])

  if (loading || eloLoading) return <div className="text-neutral-500">Loading…</div>
  if (error || eloError) return <div className="text-red-400">{error ?? eloError}</div>
  if (!models || !meta) return null

  const orgs = new Set(models.map((m) => m.dev).filter(Boolean)).size
  const stats = [
    { label: 'Models', value: fmtCount(meta.counts.models) },
    { label: 'Organizations', value: fmtCount(orgs) },
    { label: 'Benchmark results', value: fmtCount(meta.counts.benchmarkResults) },
    { label: 'Price points', value: fmtCount(meta.counts.priceComponents) },
    { label: 'Data as of', value: meta.generatedAt.slice(0, 10) },
    ...(deepsweSignal
      ? [
          {
            label: 'DeepSWE',
            value: deepsweSignal.score,
            detail: deepsweSignal.modelName,
            slug: deepsweSignal.modelSlug,
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-6">
      <div className={`grid grid-cols-1 sm:grid-cols-2 gap-3 ${deepsweSignal ? 'md:grid-cols-3 xl:grid-cols-6' : 'md:grid-cols-5'}`}>
        {stats.map((s) => {
          const slug = 'slug' in s ? s.slug : undefined

          const content = (
            <>
              <div className="text-xl font-semibold text-neutral-100">{s.value}</div>
              <div className="text-xs text-neutral-500">{s.label}</div>
              {'detail' in s ? <div className="mt-1 truncate text-[11px] text-cyan-300">{s.detail}</div> : null}
            </>
          )

          return typeof slug === 'string' && slug.length > 0 ? (
            <button
              key={s.label}
              onClick={() => navigate(`/models/${encodeURIComponent(slug)}`)}
              className="rounded-lg border border-cyan-900 bg-neutral-900 p-4 text-left hover:border-cyan-600"
            >
              {content}
            </button>
          ) : (
            <div key={s.label} className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
              {content}
            </div>
          )
        })}
      </div>

      {overviewInsights.length > 0 ? (
        <section>
          <div className="mb-3">
            <h2 className="text-base font-semibold text-neutral-100">What changed</h2>
            <p className="mt-1 text-xs text-neutral-500">Current leaders and movement derived from live model data.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {overviewInsights.map((insight) => (
              <button
                key={insight.key}
                onClick={() => openModel(insight.slug)}
                className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition hover:border-cyan-700"
              >
                <div className="text-[10px] uppercase tracking-wider text-neutral-500">{insight.label}</div>
                <div className="mt-2 truncate text-sm font-semibold text-neutral-100" title={insight.value}>
                  {insight.value}
                </div>
                <div className="mt-1 text-xs text-cyan-300">{insight.detail}</div>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {bestCategoryRows.length > 0 ? (
        <section>
          <div className="mb-3">
            <h2 className="text-base font-semibold text-neutral-100">Best for each category</h2>
            <p className="mt-1 text-xs text-neutral-500">Top percentile model in each league category.</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            {bestCategoryRows.map(({ category, row, cell }) => (
              <button
                key={category.key}
                onClick={() => openModel(row.slug)}
                className="rounded-lg border border-neutral-800 bg-neutral-900 p-3 text-left transition hover:border-cyan-700"
              >
                <div className="text-[10px] uppercase tracking-wider text-neutral-500">{category.label}</div>
                <div className="mt-2 truncate text-sm font-semibold text-neutral-100" title={row.name}>
                  {shortName(row.slug)}
                </div>
                <div className="mt-1 text-xs text-emerald-300">{fmtPercent(cell.percentile)}</div>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-neutral-100">Category League Table</h2>
            <p className="mt-1 max-w-3xl text-xs text-neutral-500">
              Latest-snapshot benchmark results are collapsed to each model&apos;s best configuration, percentile-scaled per
              benchmark, averaged by category, then blended across the scored categories.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-xs text-neutral-500" htmlFor="league-sort">
              Sort
            </label>
            <select
              id="league-sort"
              value={leagueSortBy}
              onChange={(event) => {
                const value = event.currentTarget.value
                if (
                  value === 'consensus' ||
                  value === 'arena' ||
                  value === 'coding' ||
                  value === 'math' ||
                  value === 'reasoning' ||
                  value === 'agentic' ||
                  value === 'knowledge'
                ) {
                  setLeagueSortBy(value)
                }
              }}
              className="rounded-md border border-neutral-700 bg-neutral-950 px-2 py-1 text-xs text-neutral-200 outline-none focus:border-neutral-500"
            >
              <option value="consensus">Blended Consensus</option>
              {LEAGUE_CATEGORIES.map((category) => (
                <option key={category.key} value={category.key}>
                  {category.label}
                </option>
              ))}
            </select>
            <button
              onClick={() => setLeagueLimit((value) => (value === 10 ? 30 : 10))}
              className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:border-neutral-500"
            >
              Show top {leagueLimit === 10 ? 30 : 10}
            </button>
          </div>
        </div>

        {displayedLeagueRows.length === 0 ? (
          <div className="rounded-lg border border-neutral-800 bg-neutral-950 py-10 text-center text-sm text-neutral-500">
            No category benchmark coverage available.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-neutral-800">
            <table className="w-full border-collapse text-left text-xs">
              <thead>
                <tr className="border-b border-neutral-800 bg-neutral-950 text-neutral-400">
                  <th className="sticky left-0 z-10 min-w-56 bg-neutral-950 px-4 py-3 font-medium">Model name</th>
                  <th className="px-3 py-3 text-center font-medium">Developer logo</th>
                  <th className="px-3 py-3 text-right font-medium">Blended Consensus</th>
                  {LEAGUE_CATEGORIES.map((category) => (
                    <th key={category.key} className="min-w-24 px-3 py-3 text-right font-medium">
                      {category.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {displayedLeagueRows.map((row, index) => {
                  const rowConfidence = confidenceTier(row.scoredSignalCount)

                  return (
                    <tr key={row.modelId} className="hover:bg-neutral-800/30">
                    <td className="sticky left-0 z-10 bg-neutral-900/95 px-4 py-3">
                      <div className="flex max-w-56 items-center gap-2">
                        <button
                          onClick={() => navigate(`/models/${encodeURIComponent(row.slug)}`)}
                          className="flex min-w-0 flex-1 items-center gap-2 text-left font-medium text-neutral-100 hover:text-cyan-300"
                        >
                          <span className="w-5 shrink-0 text-right text-[10px] text-neutral-500">#{index + 1}</span>
                          <span className="truncate" title={row.name}>
                            {row.name}
                          </span>
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation()
                            openModel(row.slug)
                          }}
                          className="shrink-0 rounded border border-neutral-700 px-1.5 py-0.5 text-[10px] text-neutral-400 hover:border-cyan-600 hover:text-cyan-300"
                          title={`Peek at ${row.name}`}
                          aria-label={`Peek at ${row.name}`}
                        >
                          Peek
                        </button>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex justify-center">
                        <LabLogo dev={row.dev} devName={row.devName} size={22} title={row.devName ?? row.dev ?? row.name} />
                      </div>
                    </td>
                    <td className="px-3 py-3 text-right font-semibold text-cyan-300">
                      <div className="flex items-center justify-end gap-2">
                        <span>{fmtPercent(row.consensus)}</span>
                        <span
                          className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium ${CONFIDENCE_CLASS[rowConfidence]}`}
                          title={`${CONFIDENCE_LABEL[rowConfidence]} confidence · ${fmtCount(
                            row.scoredSignalCount,
                          )} scored signals`}
                        >
                          {fmtCount(row.scoredSignalCount)}
                        </span>
                      </div>
                    </td>
                    {LEAGUE_CATEGORIES.map((category) => {
                      const cell = row.categoryScores[category.key]
                      if (!cell) {
                        return (
                          <td key={category.key} className="px-3 py-3 text-right text-neutral-700">
                            —
                          </td>
                        )
                      }

                      const tone =
                        cell.percentile >= 85
                          ? 'bg-emerald-950/70 text-emerald-300'
                          : cell.percentile >= 65
                            ? 'bg-teal-950/60 text-teal-300'
                            : cell.percentile >= 40
                              ? 'bg-amber-950/50 text-amber-300'
                              : 'bg-red-950/50 text-red-300'

                      return (
                        <td
                          key={category.key}
                          className={`px-3 py-3 text-right font-medium ${tone}`}
                          title={`${category.label}: ${fmtPercent(cell.percentile)} percentile average across ${fmtCount(
                            cell.benchmarkCount,
                          )} benchmark${cell.benchmarkCount === 1 ? '' : 's'}`}
                        >
                          <div>{fmtPercent(cell.percentile)}</div>
                          <div className="text-[10px] opacity-70">{fmtCount(cell.benchmarkCount)} bench</div>
                        </td>
                      )
                    })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h2 className="mr-4 text-base font-semibold text-neutral-100">
            Price vs ELO frontier
          </h2>
          <button
            onClick={() => setShowPareto((v) => !v)}
            className={`rounded-full border px-3 py-1 text-xs ${
              showPareto
                ? 'border-pink-500 bg-pink-950 text-pink-300'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            Pareto frontier
          </button>
          <button
            onClick={() => setOpenOnly((v) => !v)}
            className={`rounded-full border px-3 py-1 text-xs ${
              openOnly
                ? 'border-emerald-500 bg-emerald-950 text-emerald-300'
                : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
            }`}
          >
            open weights
          </button>
          {devs.map((d) => (
            <button
              key={d}
              onClick={() => setDevFilter((cur) => (cur === d ? null : d))}
              className={`rounded-full border px-3 py-1 text-xs ${
                devFilter === d
                  ? 'border-neutral-300 bg-neutral-800 text-white'
                  : 'border-neutral-700 text-neutral-400 hover:border-neutral-500'
              }`}
              style={{ borderColor: devFilter === d ? colorForDark(d) : undefined }}
            >
              <LabLogo dev={d} size={16} showLabel labelClassName="truncate" />
            </button>
          ))}
        </div>
        <div className="mb-3 flex flex-wrap items-center gap-3 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
          <button
            onClick={() => {
              if (scrubIndex != null && scrubIndex >= months.length - 1) setScrubIndex(0)
              setPlaying((value) => !value)
            }}
            className="rounded-full border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:border-neutral-500"
          >
            {playing ? 'Pause' : 'Play'}
          </button>
          <label className="min-w-28 text-xs text-neutral-400" htmlFor="overview-month-scrub">
            {selectedMonthLabel}
          </label>
          <input
            id="overview-month-scrub"
            type="range"
            min={0}
            max={Math.max(months.length - 1, 0)}
            value={scrubIndex ?? Math.max(months.length - 1, 0)}
            onChange={(event) => {
              setPlaying(false)
              setScrubIndex(Number(event.currentTarget.value))
            }}
            className="min-w-56 flex-1 accent-pink-500"
          />
        </div>
        <p className="mb-2 text-xs text-neutral-500">
          {isHistorical
            ? `LMArena text ELO as of ${selectedMonthLabel} vs current output price. Diamonds = open weights. Click a dot for details.`
            : 'Latest LMArena text ELO vs output price. Diamonds = open weights. Click a dot for details.'}
        </p>
        {points.length === 0 ? (
          <div className="py-16 text-center text-neutral-500">No models match.</div>
        ) : (
          <div ref={chartRef} className="h-[480px] w-full" />
        )}
      </div>
    </div>
  )
}
