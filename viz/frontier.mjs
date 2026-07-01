import * as Plot from '@observablehq/plot'
import { resolve } from 'node:path'
import { queryRows, newDocument, finalizeToPng, OUT_DIR } from './lib/render.mjs'
import {
  WIDTH,
  HEIGHT,
  colorFor,
  shortName,
  plotStyle,
  HIGHLIGHT,
  GRID,
  AXIS,
  NEUTRAL
} from './lib/theme.mjs'

const SQL = `
SELECT m.canonical_slug AS slug, m.developer_id AS developer, br.score AS score, MAX(CASE WHEN pc.component='input_token' THEN pc.normalized_usd_per_1m_tokens END) AS in_1m, MAX(CASE WHEN pc.component='output_token' THEN pc.normalized_usd_per_1m_tokens END) AS out_1m FROM benchmark_result br JOIN model m ON m.id=br.model_id LEFT JOIN price_component pc ON pc.model_id=m.id AND pc.source_id='models_dev' WHERE br.benchmark_id='swe_bench_verified' GROUP BY m.id
`

function isPresent(value) {
  return value !== null && value !== undefined
}

function prepareRows(rows) {
  const points = rows
    .filter((row) => isPresent(row.score) && isPresent(row.in_1m) && isPresent(row.out_1m))
    .map((row) => ({
      slug: row.slug,
      developer: row.developer,
      score: Number(row.score),
      scorePercent: Number(row.score) * 100,
      output_1m: Number(row.out_1m),
      label: shortName(row.slug),
      color: colorFor(row.developer),
      onFrontier: false
    }))
    .filter(
      (row) => Number.isFinite(row.score) && Number.isFinite(row.output_1m) && row.output_1m > 0
    )

  for (const point of points) {
    point.onFrontier = !points.some(
      (other) =>
        other !== point &&
        other.output_1m <= point.output_1m &&
        other.score >= point.score &&
        (other.output_1m < point.output_1m || other.score > point.score)
    )
  }

  return points
}

const points = prepareRows(queryRows(SQL))
if (points.length === 0) {
  throw new Error('No SWE-bench Verified rows with complete models.dev token pricing.')
}

const frontier = points
  .filter((point) => point.onFrontier)
  .sort((a, b) => a.output_1m - b.output_1m || b.score - a.score)

// Tight y-domain so the data fills the frame instead of anchoring at 0.
const scores = points.map((p) => p.scorePercent)
const yMin = Math.floor((Math.min(...scores) - 4) / 5) * 5
const yMax = Math.ceil((Math.max(...scores) + 6) / 5) * 5

// Greedy vertical declutter for frontier labels (they cluster at low price).
// Work in score-percent units; enforce a minimum gap, then keep within domain.
const minGap = (yMax - yMin) * 0.032
const labelPts = frontier
  .map((p) => ({ ...p, labelY: p.scorePercent }))
  .sort((a, b) => b.labelY - a.labelY)
for (let i = 1; i < labelPts.length; i += 1) {
  const gap = labelPts[i - 1].labelY - labelPts[i].labelY
  if (gap < minGap) {
    labelPts[i].labelY = labelPts[i - 1].labelY - minGap
  }
}
const overflow = yMin + minGap - labelPts.at(-1).labelY
if (overflow > 0) {
  for (const p of labelPts) {
    p.labelY += overflow
  }
}

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 96,
  marginBottom: 60,
  marginLeft: 70,
  x: {
    type: 'log',
    grid: false,
    tickFormat: (d) => `$${d}`,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  y: {
    domain: [yMin, yMax],
    grid: true,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  marks: [
    Plot.ruleY([yMin], { stroke: AXIS, strokeWidth: 1 }),
    Plot.line(frontier, {
      x: 'output_1m',
      y: 'scorePercent',
      stroke: HIGHLIGHT,
      strokeWidth: 2.4,
      strokeOpacity: 0.56,
      strokeDasharray: '4 4',
      curve: 'linear'
    }),
    Plot.dot(
      points.filter((point) => !point.onFrontier),
      {
        x: 'output_1m',
        y: 'scorePercent',
        r: 4.5,
        fill: NEUTRAL,
        fillOpacity: 0.32,
        stroke: 'none'
      }
    ),
    Plot.dot(frontier, {
      x: 'output_1m',
      y: 'scorePercent',
      r: 7,
      fill: (point) => point.color,
      stroke: '#111111',
      strokeWidth: 1.3
    }),
    Plot.link(labelPts, {
      x1: 'output_1m',
      y1: 'scorePercent',
      x2: 'output_1m',
      y2: 'labelY',
      stroke: (point) => point.color,
      strokeOpacity: 0.3,
      strokeWidth: 1
    }),
    Plot.text(labelPts, {
      x: 'output_1m',
      y: 'labelY',
      text: 'label',
      fill: (point) => point.color,
      dx: 9,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: 12,
      fontWeight: 600
    })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID
  }
})

await finalizeToPng(chart, {
  title: 'Price vs. capability frontier',
  subtitle:
    'SWE-bench Verified (% resolved) vs $/1M output tokens · red = Pareto frontier · Source: Epoch AI + models.dev',
  yCaption: 'SWE-bench Verified (% resolved)',
  out: resolve(OUT_DIR, 'frontier_swe_bench_verified.png')
})
