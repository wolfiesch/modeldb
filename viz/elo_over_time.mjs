import * as Plot from '@observablehq/plot'
import { resolve } from 'node:path'
import { queryRows, newDocument, finalizeToPng, OUT_DIR } from './lib/render.mjs'
import { WIDTH, HEIGHT, MS_PER_DAY, colorFor, shortName, plotStyle, AXIS } from './lib/theme.mjs'

const query = `
  SELECT br.model_id, m.canonical_slug AS slug, m.developer_id AS developer,
         br.measured_at AS date, MAX(br.score) AS score
  FROM benchmark_result br
  JOIN model m ON m.id=br.model_id
  WHERE br.benchmark_id='lmarena_text_overall' AND br.model_id IS NOT NULL
  GROUP BY br.model_id, br.measured_at
  ORDER BY br.measured_at
`

function topSeries(rawRows) {
  const bySlug = new Map()

  for (const row of rawRows) {
    const slug = row.slug
    const points = bySlug.get(slug) ?? []
    points.push({
      slug,
      developer: row.developer,
      date: new Date(`${row.date}T00:00:00Z`),
      score: Number(row.score)
    })
    bySlug.set(slug, points)
  }

  return [...bySlug.values()]
    .filter((points) => points.length >= 8)
    .map((points) => points.sort((a, b) => a.date - b.date))
    .map((points) => ({ points, latest: points.at(-1) }))
    .sort((a, b) => b.latest.score - a.latest.score)
    .slice(0, 12)
    .map(({ points }) => points)
}

function adjustedLabels(series, labelDate, yMin, yMax) {
  const minimumGap = 19
  const scale = (HEIGHT - 170) / (yMax - yMin)
  const labels = series
    .map((points) => ({
      ...points.at(-1),
      label: shortName(points.at(-1).slug),
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

  const bottomOverflow = yMin + 6 - labels.at(-1).labelScore
  if (bottomOverflow > 0) {
    for (const label of labels) {
      label.labelScore += bottomOverflow
    }
  }

  return labels.sort((a, b) => String(a.slug).localeCompare(String(b.slug)))
}

const rawRows = queryRows(query)
const series = topSeries(rawRows)
const rows = series.flat()

if (rows.length === 0) {
  throw new Error('No linked LMArena Text Overall rows matched the renderer filters.')
}

const slugs = series.map((points) => points[0].slug)
const colors = series.map((points) => colorFor(points[0].developer))
const dates = rows.map((row) => row.date)
const scores = rows.map((row) => row.score)
const minDate = new Date(Math.min(...dates))
const maxDate = new Date(Math.max(...dates))
const labelDate = new Date(maxDate.getTime() + 22 * MS_PER_DAY)
const xMax = new Date(maxDate.getTime() + 115 * MS_PER_DAY)
const yMin = Math.floor((Math.min(...scores) - 20) / 25) * 25
const yMax = Math.ceil((Math.max(...scores) + 22) / 25) * 25
const labels = adjustedLabels(series, labelDate, yMin, yMax)

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 238,
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
  color: {
    domain: slugs,
    range: colors
  },
  marks: [
    Plot.ruleY([yMin], { stroke: AXIS, strokeWidth: 1 }),
    Plot.line(rows, {
      x: 'date',
      y: 'score',
      z: 'slug',
      stroke: 'slug',
      strokeWidth: 3.2,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      curve: 'catmull-rom'
    }),
    Plot.dot(
      series.map((points) => points.at(-1)),
      {
        x: 'date',
        y: 'score',
        fill: 'slug',
        stroke: '#ffffff',
        strokeWidth: 2.2,
        r: 5
      }
    ),
    Plot.link(labels, {
      x1: 'date',
      y1: 'score',
      x2: 'labelDate',
      y2: 'labelScore',
      stroke: 'slug',
      strokeOpacity: 0.34,
      strokeWidth: 1.2
    }),
    Plot.text(labels, {
      x: 'labelDate',
      y: 'labelScore',
      text: 'label',
      fill: 'slug',
      textAnchor: 'start',
      fontSize: 17,
      fontWeight: 650,
      lineAnchor: 'middle',
      dx: 8
    })
  ],
  style: plotStyle
})

await finalizeToPng(chart, {
  title: 'The LMArena ELO race',
  subtitle: 'Text Overall · best variant per model per day · Source: LMArena',
  yCaption: 'Bradley–Terry rating',
  out: resolve(OUT_DIR, 'elo_over_time_lmarena_text_overall.png')
})
