import * as Plot from '@observablehq/plot'
import { resolve } from 'node:path'
import { queryRows, newDocument, finalizeToPng, OUT_DIR } from './lib/render.mjs'
import {
  WIDTH,
  HEIGHT,
  MS_PER_DAY,
  shortName,
  plotStyle,
  HIGHLIGHT,
  GRID,
  AXIS,
  INK,
  MUTED
} from './lib/theme.mjs'

const SQL = `
  SELECT m.canonical_slug AS slug, br.measured_at AS date, br.score AS score
  FROM benchmark_result br
  JOIN model m ON m.id=br.model_id
  WHERE br.benchmark_id='lmarena_text_overall'
    AND m.developer_id='anthropic'
  ORDER BY br.measured_at, m.canonical_slug
`

const SONNET_5_RELEASE = new Date('2026-06-30T00:00:00Z')
const ANTHROPIC_ORANGE = '#d97757'

function seriesBySlug(rawRows) {
  const bySlug = new Map()

  for (const row of rawRows) {
    const score = Number(row.score)
    if (!Number.isFinite(score)) {continue}

    const points = bySlug.get(row.slug) ?? []
    points.push({
      slug: row.slug,
      date: new Date(`${row.date}T00:00:00Z`),
      score
    })
    bySlug.set(row.slug, points)
  }

  return [...bySlug.values()]
    .map((points) => points.sort((a, b) => a.date - b.date))
    .filter((points) => points.length > 0)
    .sort((a, b) => a[0].date - b[0].date || a[0].slug.localeCompare(b[0].slug))
}

function warmColor(index, total) {
  const t = total <= 1 ? 1 : index / (total - 1)
  const lightness = 84 - t * 26
  const saturation = 46 + t * 32
  return `hsl(15 ${saturation}% ${lightness}%)`
}

function annotateSeries(series) {
  const total = series.length

  return series.map((points, index) => {
    const color = index === total - 1 ? ANTHROPIC_ORANGE : warmColor(index, total)
    const opacity = 0.24 + (index / Math.max(1, total - 1)) * 0.68
    const width = 1.7 + (index / Math.max(1, total - 1)) * 2.2

    return points.map((point) => ({
      ...point,
      label: shortName(point.slug),
      color,
      opacity,
      width
    }))
  })
}

function adjustedLabels(series, labelDate, yMin, yMax) {
  const minimumGap = 22
  const scale = (HEIGHT - 174) / (yMax - yMin)
  const labels = series
    .map((points) => ({
      ...points.at(-1),
      labelDate,
      labelScore: points.at(-1).score
    }))
    .sort((a, b) => b.score - a.score)

  for (let index = 1; index < labels.length; index += 1) {
    const previous = labels[index - 1]
    const current = labels[index]
    const pixelGap = (previous.labelScore - current.labelScore) * scale
    if (pixelGap < minimumGap) {
      current.labelScore = previous.labelScore - minimumGap / scale
    }
  }

  const bottomOverflow = yMin + 8 - labels.at(-1).labelScore
  if (bottomOverflow > 0) {
    for (const label of labels) {
      label.labelScore += bottomOverflow
    }
  }

  const topOverflow = labels[0].labelScore - (yMax - 8)
  if (topOverflow > 0) {
    for (const label of labels) {
      label.labelScore -= topOverflow
    }
  }

  return labels.sort((a, b) => a.slug.localeCompare(b.slug))
}

const rawRows = queryRows(SQL)
const baseSeries = seriesBySlug(rawRows)
const series = annotateSeries(baseSeries)
const rows = series.flat()

if (rows.length === 0) {
  throw new Error('No Anthropic Claude LMArena Text Overall rows matched the renderer filters.')
}

const dates = rows.map((row) => row.date)
const scores = rows.map((row) => row.score)
const minDate = new Date(Math.min(...dates))
const latestDataDate = new Date(Math.max(...dates))
const labelDate = new Date(SONNET_5_RELEASE.getTime() + 20 * MS_PER_DAY)
const xMax = new Date(SONNET_5_RELEASE.getTime() + 128 * MS_PER_DAY)
const yMin = Math.floor((Math.min(...scores) - 24) / 25) * 25
const yMax = Math.ceil((Math.max(...scores) + 30) / 25) * 25
const labels = adjustedLabels(series, labelDate, yMin, yMax)
const latestPoints = series.map((points) => points.at(-1))
const launchAnnotation = [
  {
    date: SONNET_5_RELEASE,
    score: yMax - 12,
    text: 'Sonnet 5 arrives\nscores pending'
  }
]

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 248,
  marginBottom: 70,
  marginLeft: 72,
  x: {
    type: 'time',
    domain: [minDate, xMax],
    ticks: '3 months',
    tickSize: 0,
    tickPadding: 12,
    label: null
  },
  y: {
    domain: [yMin, yMax],
    grid: true,
    ticks: 8,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  marks: [
    Plot.ruleY([yMin], { stroke: AXIS, strokeWidth: 1 }),
    Plot.ruleX([SONNET_5_RELEASE], {
      stroke: HIGHLIGHT,
      strokeWidth: 2.4,
      strokeOpacity: 0.9,
      strokeDasharray: '6 7'
    }),
    Plot.line(rows, {
      x: 'date',
      y: 'score',
      z: 'slug',
      stroke: 'color',
      strokeOpacity: 'opacity',
      strokeWidth: 'width',
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      curve: 'catmull-rom'
    }),
    Plot.dot(latestPoints, {
      x: 'date',
      y: 'score',
      r: 4.8,
      fill: 'color',
      fillOpacity: 0.92,
      stroke: '#ffffff',
      strokeWidth: 2
    }),
    Plot.link(labels, {
      x1: 'date',
      y1: 'score',
      x2: 'labelDate',
      y2: 'labelScore',
      stroke: 'color',
      strokeOpacity: 0.35,
      strokeWidth: 1.2
    }),
    Plot.text(labels, {
      x: 'labelDate',
      y: 'labelScore',
      text: 'label',
      fill: 'color',
      textAnchor: 'start',
      lineAnchor: 'middle',
      dx: 8,
      fontSize: 15,
      fontWeight: 650
    }),
    Plot.text(launchAnnotation, {
      x: 'date',
      y: 'score',
      text: 'text',
      fill: HIGHLIGHT,
      textAnchor: 'end',
      lineAnchor: 'top',
      dx: -12,
      dy: 3,
      fontSize: 21,
      fontWeight: 800,
      lineHeight: 1.05
    }),
    Plot.text(
      [
        {
          date: latestDataDate,
          score: yMin + 12,
          text: 'Claude-only LMArena history; no Sonnet 5 ELO yet'
        }
      ],
      {
        x: 'date',
        y: 'score',
        text: 'text',
        fill: MUTED,
        textAnchor: 'end',
        fontSize: 13,
        fontWeight: 550
      }
    )
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID,
    color: INK
  }
})

await finalizeToPng(chart, {
  title: 'The Claude arena climb',
  subtitle: 'LMArena Text Overall ELO by generation · Sonnet 5 joins at launch, scores pending',
  yCaption: 'Arena ELO',
  out: resolve(OUT_DIR, 'lineage_elo.png')
})
