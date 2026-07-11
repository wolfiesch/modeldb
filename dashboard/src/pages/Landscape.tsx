import { useMemo } from 'react'
import { loadBenchmarks, loadElo, loadMeta, loadModels, loadPrices, useData } from '../lib/data'
import { labLabel } from '../lib/labs'
import { colorForDark, shortName } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import ChartState, { resolveChartStatus } from '../components/ChartState'
import { useModelDrawer } from '../components/ModelDrawer'
import { fmtDate, fmtElo, fmtScore, fmtTokens } from '../lib/format'
import type { EChartsCoreOption } from 'echarts/core'

interface Point {
  slug: string
  name: string
  dev: string | null
}

const loadTextOverallElo = () => loadElo('text_overall')
interface FrontierPricePoint {
  value: [number, number]
  name: string
  price: number
}

function monthStart(ts: number) {
  const d = new Date(ts)
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)
}

function monthEnd(ts: number) {
  const d = new Date(ts)
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0, 23, 59, 59, 999)
}

function addMonth(ts: number) {
  const d = new Date(ts)
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)
}


function modeNonZero(values: number[]) {
  const counts = new Map<number, number>()
  for (const value of values) {
    if (value <= 0) continue
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  let best: number | null = null
  let bestCount = 0
  for (const [value, count] of counts) {
    if (count > bestCount || (count === bestCount && (best == null || value < best))) {
      best = value
      bestCount = count
    }
  }
  return best
}

const darkAxis = {
  axisLabel: { color: '#a3a3a3' },
  nameTextStyle: { color: '#737373' },
  splitLine: { lineStyle: { color: '#262626' } },
}

export default function Landscape() {
  const { data: models, loading, error } = useData(loadModels)
  const { data: benchmarks, loading: benchmarksLoading, error: benchmarksError } = useData(loadBenchmarks)
  const { data: prices, loading: pricesLoading, error: pricesError } = useData(loadPrices)
  const { data: textOverallElo, loading: eloLoading, error: eloError } = useData(loadTextOverallElo)
  const { data: meta } = useData(loadMeta)
  const { openModel } = useModelDrawer()

  const openPoint = (params: unknown) => {
    const p = params as { data?: { meta?: Point } }
    if (p.data?.meta?.slug) openModel(p.data.meta.slug)
  }

  const ctxPoints = useMemo(
    () => models?.filter((m) => m.released && m.ctx != null && m.ctx > 0) ?? [],
    [models],
  )

  const ctxOutlierLabels = useMemo(() => {
    const labels = new Set<string>()
    const ordered = [...ctxPoints].sort((a, b) => (b.ctx ?? 0) - (a.ctx ?? 0))
    for (const model of ordered.slice(0, 3)) labels.add(model.slug)
    for (const model of ordered.slice(-3)) labels.add(model.slug)
    return labels
  }, [ctxPoints])

  const freshPoints = useMemo(
    () => models?.filter((m) => m.released && m.cutoff && /^\d{4}-\d{2}/.test(m.cutoff)) ?? [],
    [models],
  )

  const gapRows = useMemo(() => {
    if (!models || !benchmarks) return []
    const benchIds = benchmarks.map((b) => b.id)
    const best = new Map<string, { open: number | null; closed: number | null }>()
    for (const m of models) {
      for (const [bid, s] of Object.entries(m.scores)) {
        if (s.selfReported === 1) continue
        const entry = best.get(bid) ?? { open: null, closed: null }
        if (m.open === 1) entry.open = Math.max(entry.open ?? -Infinity, s.score)
        else entry.closed = Math.max(entry.closed ?? -Infinity, s.score)
        best.set(bid, entry)
      }
    }
    return benchIds
      .filter((id) => best.has(id) && !id.startsWith('lmarena_'))
      .map((id) => ({
        name: benchmarks.find((b) => b.id === id)?.name ?? id,
        ...best.get(id)!,
      }))
  }, [models, benchmarks])

  // 1. Context-window arms race
  const ctxOption = useMemo<EChartsCoreOption | null>(() => {
    if (ctxPoints.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 72, right: 24, top: 24, bottom: 48 },
      xAxis: { type: 'time', name: 'Release date', nameLocation: 'middle', nameGap: 32, ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => fmtDate(new Date(value).toISOString().slice(0, 10)) }, splitLine: { show: false } },
      yAxis: { type: 'log', name: 'Context window (tokens, log)', ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => fmtTokens(value) } },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: Point; value: [string, number] } }) =>
          `<b>${p.data.meta.name}</b><br/>${labLabel(p.data.meta.dev)}<br/>${fmtDate(p.data.value[0])} · ${fmtTokens(p.data.value[1])} tokens`,
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 9,
          data: ctxPoints.map((m) => ({
            value: [m.released, m.ctx],
            meta: { slug: m.slug, name: m.name, dev: m.dev },
            itemStyle: { color: colorForDark(m.dev), opacity: 0.8 },
            label: ctxOutlierLabels.has(m.slug)
              ? {
                  show: true,
                  formatter: shortName(m.slug),
                  position: 'top',
                  color: '#d4d4d4',
                  fontSize: 10,
                  backgroundColor: '#171717',
                  borderColor: '#262626',
                  borderWidth: 1,
                  borderRadius: 4,
                  padding: [2, 4],
                }
              : undefined,
          })),
        },
      ],
    }
  }, [ctxPoints, ctxOutlierLabels])

  // 2. Knowledge freshness (cutoff vs release)
  const freshOption = useMemo<EChartsCoreOption | null>(() => {
    if (freshPoints.length === 0) return null
    const dates = freshPoints.flatMap((m) => [Date.parse(m.released!), Date.parse(m.cutoff! + (m.cutoff!.length === 7 ? '-01' : ''))])
    const min = Math.min(...dates)
    const max = Math.max(...dates)
    return {
      backgroundColor: 'transparent',
      grid: { left: 72, right: 24, top: 24, bottom: 48 },
      xAxis: { type: 'time', name: 'Release date', nameLocation: 'middle', nameGap: 32, ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => fmtDate(new Date(value).toISOString().slice(0, 10)) }, splitLine: { show: false } },
      yAxis: { type: 'time', name: 'Knowledge cutoff', ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => fmtDate(new Date(value).toISOString().slice(0, 10)) } },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: Point & { released: string; cutoff: string } } }) =>
          `<b>${p.data.meta.name}</b><br/>${labLabel(p.data.meta.dev)}<br/>released ${fmtDate(p.data.meta.released)} · cutoff ${fmtDate(p.data.meta.cutoff.length === 7 ? `${p.data.meta.cutoff}-01` : p.data.meta.cutoff)}`, 
      },
      series: [
        {
          type: 'scatter',
          symbolSize: 9,
          data: freshPoints.map((m) => ({
            value: [
              m.released,
              m.cutoff!.length === 7 ? `${m.cutoff}-01` : m.cutoff,
            ],
            meta: { slug: m.slug, name: m.name, dev: m.dev, released: m.released, cutoff: m.cutoff },
            itemStyle: { color: colorForDark(m.dev), opacity: 0.8 },
          })),
        },
        {
          // cutoff == release diagonal reference
          type: 'line',
          showSymbol: false,
          silent: true,
          data: [
            [min, min],
            [max, max],
          ],
          lineStyle: { color: '#525252', type: 'dashed', width: 1 },
        },
      ],
    }
  }, [freshPoints])

  // 3. Open vs closed best score per benchmark (independent results only)
  const gapOption = useMemo<EChartsCoreOption | null>(() => {
    if (gapRows.length === 0) return null
    return {
      backgroundColor: 'transparent',
      grid: { left: 120, right: 24, top: 40, bottom: 32 },
      legend: { textStyle: { color: '#a3a3a3' }, top: 0 },
      xAxis: { type: 'value', ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => fmtScore(value) } },
      yAxis: { type: 'category', data: gapRows.map((r) => r.name), axisLabel: { color: '#d4d4d4', fontSize: 11 } },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (value: number | null) => fmtScore(value),
      },
      series: [
        {
          name: 'Closed',
          type: 'bar',
          data: gapRows.map((r) => r.closed),
          itemStyle: { color: '#737373' },
          barMaxWidth: 12,
        },
        {
          name: 'Open weights',
          type: 'bar',
          data: gapRows.map((r) => r.open),
          itemStyle: { color: '#10b981' },
          barMaxWidth: 12,
        },
      ],
    }
  }, [gapRows])

  // 4. Cost of frontier intelligence over time
  const costTrend = useMemo<{ option: EChartsCoreOption; usesCurrentPrices: boolean; rowCount: number } | null>(() => {
    if (!models || !prices || !textOverallElo) return null

    const modelById = new Map(models.map((model) => [model.id, model] as const))
    const priceRowsByModel = new Map(prices.map((entry) => [entry.modelId, entry.rows] as const))
    const allTimes = textOverallElo.series.flatMap((series) => series.t)
    if (allTimes.length === 0) return null

    const firstMonth = monthStart(Math.min(...allTimes))
    const lastMonth = monthStart(Math.max(...allTimes))
    const months: number[] = []
    for (let month = firstMonth; month <= lastMonth; month = addMonth(month)) {
      months.push(month)
    }

    const currentPrice = (modelId: number) => {
      const model = modelById.get(modelId)
      return model?.priceOut != null && model.priceOut > 0 ? model.priceOut : null
    }

    const windowPrice = (modelId: number, at: number) => {
      const rows = priceRowsByModel.get(modelId) ?? []
      const values = rows
        .filter((row) => {
          if (row.component !== 'output_token' || row.sourceId !== 'models_dev' || row.usdPer1m == null) return false
          if (!row.validFrom || Date.parse(row.validFrom) > at) return false
          return !row.validTo || Date.parse(row.validTo) >= at
        })
        .map((row) => row.usdPer1m!)
      return modeNonZero(values)
    }

    const buildPoints = (threshold: number, useCurrentPrices: boolean): FrontierPricePoint[] => {
      const latestEloByModel = new Map<number, number>()
      const cursorByModel = new Map<number, number>()
      const points: FrontierPricePoint[] = []

      for (const month of months) {
        const end = monthEnd(month)
        for (const series of textOverallElo.series) {
          let cursor = cursorByModel.get(series.modelId) ?? 0
          while (cursor < series.t.length && series.t[cursor] <= end) {
            latestEloByModel.set(series.modelId, series.elo[cursor])
            cursor += 1
          }
          cursorByModel.set(series.modelId, cursor)
        }

        let cheapest: { modelId: number; price: number } | null = null
        for (const [modelId, elo] of latestEloByModel) {
          if (elo < threshold) continue
          const price = useCurrentPrices ? currentPrice(modelId) : windowPrice(modelId, end)
          if (price == null) continue
          if (!cheapest || price < cheapest.price) cheapest = { modelId, price }
        }

        if (cheapest) {
          points.push({
            value: [month, cheapest.price],
            name: modelById.get(cheapest.modelId)?.name ?? `Model ${cheapest.modelId}`,
            price: cheapest.price,
          })
        }
      }

      return points
    }

    const windowFrontier = buildPoints(1400, false)
    const windowTop = buildPoints(1450, false)
    const currentFrontier = buildPoints(1400, true)
    const currentTop = buildPoints(1450, true)
    const useCurrentPrices =
      currentFrontier.length + currentTop.length > 0 &&
      windowFrontier.length + windowTop.length < (currentFrontier.length + currentTop.length) * 0.6
    const frontier = useCurrentPrices ? currentFrontier : windowFrontier
    const top = useCurrentPrices ? currentTop : windowTop
    if (frontier.length === 0 && top.length === 0) return null

    return {
      usesCurrentPrices: useCurrentPrices,
      option: {
        backgroundColor: 'transparent',
        grid: { left: 72, right: 24, top: 40, bottom: 48 },
        legend: { textStyle: { color: '#a3a3a3' }, top: 0 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' },
          formatter: (params: Array<{ seriesName: string; data?: FrontierPricePoint }>) =>
            params
              .filter((p) => p.data)
              .map((p, index) => {
                const data = p.data!
                const month = fmtDate(new Date(data.value[0]).toISOString().slice(0, 10))
                const price = `$${fmtScore(data.price)}/1M output`
                const header = index === 0 ? `<b>${month}</b><br/>` : ''
                return `${header}${p.seriesName}: ${data.name}<br/>${price}`
              })
              .join('<br/>'),
        },
        xAxis: { type: 'time', name: 'Month', nameLocation: 'middle', nameGap: 32, ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => fmtDate(new Date(value).toISOString().slice(0, 10)) }, splitLine: { show: false } },
        yAxis: { type: 'log', name: 'USD per 1M output tokens', ...darkAxis, axisLabel: { color: '#a3a3a3', formatter: (value: number) => `$${fmtScore(value)}` } },
        series: [
          {
            name: `Frontier tier, ELO ≥ ${fmtElo(1400)}`,
            type: 'line',
            step: 'end',
            showSymbol: false,
            data: frontier,
            lineStyle: { color: '#10b981', width: 3 },
            itemStyle: { color: '#10b981' },
          },
          {
            name: `Top tier, ELO ≥ ${fmtElo(1450)}`,
            type: 'line',
            step: 'end',
            showSymbol: false,
            data: top,
            lineStyle: { color: '#e0245e', width: 3 },
            itemStyle: { color: '#e0245e' },
          },
        ],
      },
      rowCount: frontier.length + top.length,
    }
  }, [models, prices, textOverallElo])

  const ctxRef = useECharts(ctxOption, openPoint)
  const freshRef = useECharts(freshOption, openPoint)
  const gapRef = useECharts(gapOption)
  const costRef = useECharts(costTrend?.option ?? null)

  const modelsStatusBase = { loading, error, total: models?.length, updated: meta?.generatedAt ? fmtDate(meta.generatedAt) : undefined }
  const ctxStatus = resolveChartStatus({ loading, error, hasData: ctxOption != null, rowCount: ctxPoints.length })
  const freshStatus = resolveChartStatus({ loading, error, hasData: freshOption != null, rowCount: freshPoints.length })
  const gapStatus = resolveChartStatus({ loading: loading || benchmarksLoading, error: error ?? benchmarksError, hasData: gapOption != null, rowCount: gapRows.length })
  const costStatus = resolveChartStatus({ loading: loading || pricesLoading || eloLoading, error: error ?? pricesError ?? eloError, hasData: costTrend != null, rowCount: costTrend?.rowCount ?? 0 })

  return (
    <div className="space-y-6">
      <h1 className="text-lg font-semibold text-neutral-100">Landscape</h1>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">
          Context-window arms race
        </h2>
        <ChartState
          status={ctxStatus}
          minHeight={420}
          emptyLabel="No models have context-window measurements."
          errorLabel="Could not load model context-window data."
          footer={{ source: 'models.dev', shown: ctxPoints.length, total: modelsStatusBase.total, updated: modelsStatusBase.updated }}
        >
          <div ref={ctxRef} className="h-[420px] w-full" />
        </ChartState>
      </div>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">Knowledge freshness</h2>
        <p className="mb-2 text-xs text-neutral-500">
          Dashed line = cutoff equals release date; distance below it is staleness at launch.
        </p>
        <ChartState
          status={freshStatus}
          minHeight={420}
          emptyLabel="No models have both release and knowledge-cutoff dates."
          errorLabel="Could not load knowledge-freshness data."
          footer={{ source: 'models.dev', shown: freshPoints.length, total: modelsStatusBase.total, updated: modelsStatusBase.updated }}
        >
          <div ref={freshRef} className="h-[420px] w-full" />
        </ChartState>
      </div>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">
          Open vs closed: best independent score per benchmark
        </h2>
        <ChartState
          status={gapStatus}
          minHeight={420}
          emptyLabel="No independent benchmark scores are available."
          errorLabel="Could not load benchmark data."
          footer={{ source: 'Artificial Analysis + benchmark providers', shown: gapRows.length, total: benchmarks?.length, updated: modelsStatusBase.updated }}
        >
          <div ref={gapRef} className="h-[420px] w-full" />
        </ChartState>
      </div>
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-2 text-sm font-semibold text-neutral-200">
          Cost of frontier intelligence over time
        </h2>
        <p className="mb-2 text-xs text-neutral-500">
          Cheapest model in each ELO tier by active models.dev output-token price
          {costTrend?.usesCurrentPrices ? '; prices are current list prices.' : '.'}
        </p>
        <ChartState
          status={costStatus}
          minHeight={420}
          emptyLabel="No price history is available for the ELO frontier tiers."
          errorLabel="Could not load frontier cost data."
          footer={{ source: costTrend?.usesCurrentPrices ? 'models.dev current prices + LMArena' : 'models.dev price history + LMArena', shown: costTrend?.rowCount, total: prices?.length, updated: modelsStatusBase.updated }}
        >
          <div ref={costRef} className="h-[420px] w-full" />
        </ChartState>
      </div>
    </div>
  )
}
