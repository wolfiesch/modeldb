import { useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { loadElo, loadModels, useData, type Model } from '../lib/data'
import { LabLogo } from '../components/LabLogo'
import { labLabel } from '../lib/labs'
import { colorForDark } from '../lib/theme'
import { useECharts } from '../lib/useECharts'
import type { EChartsCoreOption } from 'echarts/core'

const loadOverall = () => loadElo('text_overall')

interface ModelPoint {
  slug: string
  name: string
  dev: string | null
  devName: string | null
  priceOut: number
  elo: number
  own: boolean
}

const darkAxis = {
  axisLabel: { color: '#a3a3a3' },
  nameTextStyle: { color: '#737373' },
  splitLine: { lineStyle: { color: '#262626' } },
}

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? 'n/a' : v >= 1000 ? v.toLocaleString() : v.toFixed(digits).replace(/\.00$/, '')

function latestReleaseSort(a: Model, b: Model) {
  if (a.released == null && b.released == null) return a.name.localeCompare(b.name)
  if (a.released == null) return 1
  if (b.released == null) return -1
  const cmp = b.released.localeCompare(a.released)
  return cmp === 0 ? a.name.localeCompare(b.name) : cmp
}

export default function DevPage() {
  const { dev = '' } = useParams()
  const navigate = useNavigate()
  const { data: models, loading: modelsLoading, error: modelsError } = useData(loadModels)
  const { data: elo, loading: eloLoading, error: eloError } = useData(loadOverall)

  const devKey = decodeURIComponent(dev).toLowerCase()

  const devModels = useMemo(() => {
    if (!models) return []
    return models.filter((m) => (m.dev ?? '').toLowerCase() === devKey)
  }, [models, devKey])

  const latestByModel = useMemo(() => {
    const latest = new Map<number, number>()
    if (!elo) return latest
    for (const s of elo.series) {
      const value = s.elo[s.elo.length - 1]
      if (value != null) latest.set(s.modelId, value)
    }
    return latest
  }, [elo])

  const modelById = useMemo(() => new Map((models ?? []).map((m) => [m.id, m])), [models])
  const devIds = useMemo(() => new Set(devModels.map((m) => m.id)), [devModels])
  const brand = colorForDark(devKey)
  const devName = devModels[0] ? labLabel(devModels[0].dev, devModels[0].devName) : labLabel(devKey)

  const fanOption = useMemo<EChartsCoreOption | null>(() => {
    if (!elo || devModels.length === 0) return null
    const rows = elo.series
      .filter((s) => devIds.has(s.modelId) && s.elo.length > 0)
      .map((s) => ({ series: s, latest: s.elo[s.elo.length - 1] ?? -Infinity }))
      .sort((a, b) => b.latest - a.latest)
    if (rows.length === 0) return null

    const opacityFor = (index: number) => {
      if (rows.length === 1) return 1
      return 1 - (index / (rows.length - 1)) * 0.65
    }

    return {
      backgroundColor: 'transparent',
      grid: { left: 56, right: 24, top: 16, bottom: 72 },
      xAxis: {
        type: 'time',
        axisLabel: { color: '#a3a3a3' },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        scale: true,
        name: 'LMArena ELO',
        ...darkAxis,
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
      series: rows.map(({ series }, index) => ({
        name: modelById.get(series.modelId)?.name ?? String(series.modelId),
        type: 'line' as const,
        showSymbol: false,
        sampling: 'lttb' as const,
        data: series.t.map((t, i) => [t, series.elo[i]]),
        lineStyle: { width: 1.7, color: brand, opacity: opacityFor(index) },
        itemStyle: { color: brand, opacity: opacityFor(index) },
        emphasis: { focus: 'series' as const, lineStyle: { width: 2.4, opacity: 1 } },
      })),
    }
  }, [brand, devIds, devModels.length, elo, modelById])

  const scatterOption = useMemo<EChartsCoreOption | null>(() => {
    if (!models || devModels.length === 0) return null
    const points: ModelPoint[] = models
      .map((m) => {
        const eloValue = latestByModel.get(m.id) ?? m.scores.lmarena_text_overall?.score
        if (m.priceOut == null || m.priceOut <= 0 || eloValue == null) return null
        const own = (m.dev ?? '').toLowerCase() === devKey
        return {
          slug: m.slug,
          name: m.name,
          dev: m.dev,
          devName: m.devName,
          priceOut: m.priceOut,
          elo: eloValue,
          own,
        }
      })
      .filter((p) => p != null)

    if (!points.some((p) => p.own)) return null

    const toDatum = (p: ModelPoint) => ({
      value: [p.priceOut, p.elo],
      meta: p,
      itemStyle: { color: p.own ? brand : '#525252', opacity: p.own ? 0.9 : 0.42 },
    })

    return {
      backgroundColor: 'transparent',
      grid: { left: 64, right: 24, top: 24, bottom: 48 },
      xAxis: {
        type: 'log',
        name: 'Output $/1M tokens (log)',
        nameLocation: 'middle',
        nameGap: 32,
        ...darkAxis,
      },
      yAxis: {
        type: 'value',
        name: 'Latest LMArena ELO',
        scale: true,
        ...darkAxis,
      },
      tooltip: {
        trigger: 'item',
        formatter: (p: { data: { meta: ModelPoint } }) => {
          const d = p.data.meta
          return `<b>${d.name}</b><br/>${labLabel(d.dev, d.devName)}<br/>$${fmt(
            d.priceOut,
          )}/1M out · ELO ${Math.round(d.elo)}`
        },
      },
      series: [
        {
          name: 'Other developers',
          type: 'scatter',
          symbolSize: 6,
          data: points.filter((p) => !p.own).map(toDatum),
        },
        {
          name: devName,
          type: 'scatter',
          symbolSize: 13,
          data: points.filter((p) => p.own).map(toDatum),
        },
      ],
    }
  }, [brand, devKey, devModels, devName, latestByModel, models])

  const fanRef = useECharts(fanOption)
  const scatterRef = useECharts(scatterOption, (params) => {
    const p = params as { data?: { meta?: ModelPoint } }
    if (p.data?.meta?.slug) navigate(`/models/${encodeURIComponent(p.data.meta.slug)}`)
  })

  if (modelsLoading || eloLoading) return <div className="text-neutral-500">Loading…</div>
  if (modelsError || eloError) return <div className="text-red-400">{modelsError ?? eloError}</div>

  if (!models || devModels.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
        <div className="mb-2 text-lg text-neutral-200">Developer not found</div>
        <div className="mb-4 text-sm text-neutral-500">No developer matching “{devKey}”.</div>
        <Link to="/models" className="text-sm text-blue-400 hover:underline">
          Back to Model Explorer
        </Link>
      </div>
    )
  }

  const tableRows = [...devModels].sort(latestReleaseSort)
  const openCount = devModels.filter((m) => m.open === 1).length

  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-3">
              <LabLogo
                dev={devModels[0].dev}
                devName={devModels[0].devName}
                size={40}
                showLabel
                labelClassName="text-2xl font-bold text-neutral-100"
                imgClassName="rounded-lg"
              />
            </div>
            <div className="text-sm text-neutral-500">Developer portfolio and price position</div>
          </div>
          <div className="grid grid-cols-2 gap-3 text-right">
            <div>
              <div className="text-xl font-semibold text-neutral-100">{devModels.length}</div>
              <div className="text-xs text-neutral-500">models</div>
            </div>
            <div>
              <div className="text-xl font-semibold text-neutral-100">{openCount}</div>
              <div className="text-xs text-neutral-500">open weights</div>
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-1 text-sm font-semibold text-neutral-200">ELO fan chart</h2>
        <p className="mb-2 text-xs text-neutral-500">
          All {devName} text-overall Arena histories. Stronger lines are higher ranked within this
          developer by latest ELO.
        </p>
        {fanOption ? (
          <div ref={fanRef} className="h-[440px] w-full" />
        ) : (
          <div className="py-16 text-center text-sm text-neutral-500">
            No LMArena history for this developer.
          </div>
        )}
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-3 text-sm font-semibold text-neutral-200">Models</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-neutral-500">
              <tr>
                <th className="px-3 py-2 font-medium">Model</th>
                <th className="px-3 py-2 font-medium">Released</th>
                <th className="px-3 py-2 text-right font-medium">Context</th>
                <th className="px-3 py-2 text-right font-medium">$ in/1M</th>
                <th className="px-3 py-2 text-right font-medium">$ out/1M</th>
                <th className="px-3 py-2 text-right font-medium">Latest ELO</th>
                <th className="px-3 py-2 font-medium">Stability</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((m) => (
                <tr
                  key={m.id}
                  onClick={() => navigate(`/models/${encodeURIComponent(m.slug)}`)}
                  className="cursor-pointer border-t border-neutral-800/60 hover:bg-neutral-800/40"
                >
                  <td className="px-3 py-2 text-neutral-100">{m.name}</td>
                  <td className="px-3 py-2 text-neutral-400">{m.released ?? 'n/a'}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">
                    {m.ctx == null ? 'n/a' : m.ctx.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right text-neutral-300">{fmt(m.priceIn)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">{fmt(m.priceOut)}</td>
                  <td className="px-3 py-2 text-right text-neutral-300">
                    {latestByModel.get(m.id) == null ? 'n/a' : Math.round(latestByModel.get(m.id)!)}
                  </td>
                  <td className="px-3 py-2 text-neutral-400">{m.stability ?? 'n/a'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-4">
        <h2 className="mb-1 text-sm font-semibold text-neutral-200">Price positioning</h2>
        <p className="mb-2 text-xs text-neutral-500">
          Output price versus latest text-overall ELO. Gray dots show the rest of the market for
          context. Click a dot for model detail.
        </p>
        {scatterOption ? (
          <div ref={scatterRef} className="h-[480px] w-full" />
        ) : (
          <div className="py-16 text-center text-sm text-neutral-500">
            No models with both a price and latest ELO.
          </div>
        )}
      </div>
    </div>
  )
}
