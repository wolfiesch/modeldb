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
  INK,
  MUTED,
  FAINT
} from './lib/theme.mjs'

const TARGET_ID = 75
const LAUNCH_SPEC = {
  input_price: 2,
  output_price: 10,
  cache_read_price: 0.2,
  context_window: 1_000_000,
  max_output: 128_000
}

const SQL = `
WITH price AS (
  SELECT
    model_id,
    MAX(CASE WHEN component = 'input_token' THEN normalized_usd_per_1m_tokens END) AS input_price,
    MAX(CASE WHEN component = 'output_token' THEN normalized_usd_per_1m_tokens END) AS output_price,
    MAX(CASE WHEN component = 'cache_read' THEN normalized_usd_per_1m_tokens END) AS cache_read_price
  FROM price_component
  WHERE source_id = 'models_dev'
  GROUP BY model_id
), caps AS (
  SELECT
    model_id,
    MAX(CASE WHEN capability = 'context_window' THEN CAST(value AS INTEGER) END) AS context_window,
    MAX(CASE WHEN capability = 'max_output' THEN CAST(value AS INTEGER) END) AS max_output
  FROM model_capability
  WHERE capability IN ('context_window', 'max_output')
  GROUP BY model_id
)
SELECT
  m.id,
  m.canonical_slug AS slug,
  m.developer_id AS developer,
  m.release_date,
  price.input_price,
  price.output_price,
  price.cache_read_price,
  caps.context_window,
  caps.max_output
FROM model m
LEFT JOIN price ON price.model_id = m.id
LEFT JOIN caps ON caps.model_id = m.id
`

const models = queryRows(SQL)
const target = models.find((model) => model.id === TARGET_ID)
if (!target) {
  throw new Error('Claude Sonnet 5 (model id 75) was not found.')
}

const formatDollars = (value) => `$${Number(value).toFixed(2)} / 1M`
const formatTokens = (value) => `${Number(value).toLocaleString('en-US')} tokens`
const isPresent = (value) => value !== null && value !== undefined && Number.isFinite(Number(value))

function specRow({ id, label, field, rawValue, biggerIsBetter, format }) {
  const targetValue = Number(rawValue)
  const values = models
    .map((model) => (model.id === TARGET_ID ? targetValue : Number(model[field])))
    .filter((value) => Number.isFinite(value) && value > 0)
  if (!Number.isFinite(targetValue) || targetValue <= 0) {
    throw new Error(`Claude Sonnet 5 is missing ${label}.`)
  }
  if (values.length === 0) {
    throw new Error(`No comparison distribution for ${label}.`)
  }

  const favorableCount = values.filter((value) => (biggerIsBetter ? value <= targetValue : value >= targetValue)).length
  const favorability = Math.max(0, Math.min(100, favorableCount / values.length * 100))
  const roundedFavorability = Math.round(favorability)
  const topPercent = Math.max(1, 100 - roundedFavorability)

  return {
    id,
    label,
    favorability,
    raw: format(targetValue),
    tag: `top ${topPercent}%`,
    caption: biggerIsBetter ? 'bigger spec ranks higher' : 'lower price ranks higher',
    n: values.length
  }
}

const rows = [
  specRow({
    id: 'input',
    label: 'Input price',
    field: 'input_price',
    rawValue: LAUNCH_SPEC.input_price,
    biggerIsBetter: false,
    format: formatDollars
  }),
  specRow({
    id: 'output',
    label: 'Output price',
    field: 'output_price',
    rawValue: LAUNCH_SPEC.output_price,
    biggerIsBetter: false,
    format: formatDollars
  }),
  specRow({
    id: 'cache_read',
    label: 'Cache-read price',
    field: 'cache_read_price',
    rawValue: LAUNCH_SPEC.cache_read_price,
    biggerIsBetter: false,
    format: formatDollars
  }),
  specRow({
    id: 'context',
    label: 'Context window',
    field: 'context_window',
    rawValue: LAUNCH_SPEC.context_window,
    biggerIsBetter: true,
    format: formatTokens
  }),
  specRow({
    id: 'max_output',
    label: 'Max output',
    field: 'max_output',
    rawValue: LAUNCH_SPEC.max_output,
    biggerIsBetter: true,
    format: formatTokens
  })
]

for (const row of rows) {
  if (!isPresent(row.favorability)) {
    throw new Error(`Invalid favorability percentile for ${row.label}.`)
  }
}

const yDomain = ['header', ...rows.map((row) => row.id), 'footer']
const modelName = `Claude ${shortName(target.slug)}`
const anthropic = colorFor(target.developer)
const header = [
  {
    id: 'header',
    x: 0,
    text: modelName,
    fill: INK,
    size: 30,
    weight: 780,
    anchor: 'start',
    dx: -8
  },
  {
    id: 'header',
    x: 100,
    text: `released ${target.release_date}`,
    fill: MUTED,
    size: 18,
    weight: 560,
    anchor: 'end',
    dx: 8
  }
]
const footer = [
  {
    id: 'footer',
    x: 0,
    text: 'Gauge fill shows favorability percentile: fuller is more favorable for every metric.',
    fill: FAINT,
    size: 14,
    weight: 500,
    anchor: 'start',
    dx: -8
  },
  {
    id: 'footer',
    x: 100,
    text: 'Source: models.dev + model capability catalog',
    fill: FAINT,
    size: 14,
    weight: 500,
    anchor: 'end',
    dx: 8
  }
]

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 124,
  marginRight: 352,
  marginBottom: 64,
  marginLeft: 390,
  x: {
    domain: [0, 100],
    axis: null,
    label: null
  },
  y: {
    domain: yDomain,
    axis: null,
    label: null,
    padding: 0.52
  },
  marks: [
    Plot.frame({ stroke: AXIS, strokeOpacity: 0.9, strokeWidth: 1.2, rx: 26 }),
    Plot.text(header, {
      x: 'x',
      y: 'id',
      text: 'text',
      dx: 'dx',
      fill: 'fill',
      textAnchor: 'anchor',
      lineAnchor: 'middle',
      fontSize: 'size',
      fontWeight: 'weight'
    }),
    Plot.link([{ x1: 0, x2: 100, y1: 'header', y2: 'header' }], {
      x1: 'x1',
      x2: 'x2',
      y1: 'y1',
      y2: 'y2',
      stroke: GRID,
      strokeWidth: 1.4,
      strokeOpacity: 0.95,
      dy: 34
    }),
    Plot.text(rows, {
      x: 0,
      y: 'id',
      text: 'label',
      dx: -34,
      dy: -9,
      fill: INK,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: 22,
      fontWeight: 760
    }),
    Plot.text(rows, {
      x: 0,
      y: 'id',
      text: 'caption',
      dx: -34,
      dy: 19,
      fill: MUTED,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: 13,
      fontWeight: 520
    }),
    Plot.link(rows, {
      x1: 0,
      x2: 100,
      y1: 'id',
      y2: 'id',
      stroke: GRID,
      strokeWidth: 24,
      strokeLinecap: 'round'
    }),
    Plot.link(rows, {
      x1: 0,
      x2: 'favorability',
      y1: 'id',
      y2: 'id',
      stroke: HIGHLIGHT,
      strokeWidth: 24,
      strokeOpacity: 0.9,
      strokeLinecap: 'round'
    }),
    Plot.dot(rows, {
      x: 'favorability',
      y: 'id',
      r: 12,
      fill: HIGHLIGHT,
      stroke: '#ffffff',
      strokeWidth: 4
    }),
    Plot.dot(rows, {
      x: 'favorability',
      y: 'id',
      r: 17,
      fill: 'none',
      stroke: anthropic,
      strokeOpacity: 0.32,
      strokeWidth: 3
    }),
    Plot.text(rows, {
      x: 'favorability',
      y: 'id',
      text: (row) => `${Math.round(row.favorability)}%`,
      dy: -32,
      fill: HIGHLIGHT,
      textAnchor: 'middle',
      lineAnchor: 'middle',
      fontSize: 13,
      fontWeight: 780
    }),
    Plot.text(rows, {
      x: 100,
      y: 'id',
      text: 'raw',
      dx: 38,
      dy: -9,
      fill: INK,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: 21,
      fontWeight: 760
    }),
    Plot.text(rows, {
      x: 100,
      y: 'id',
      text: 'tag',
      dx: 38,
      dy: 19,
      fill: HIGHLIGHT,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: 14,
      fontWeight: 780
    }),
    Plot.text(footer, {
      x: 'x',
      y: 'id',
      text: 'text',
      dx: 'dx',
      fill: 'fill',
      textAnchor: 'anchor',
      lineAnchor: 'middle',
      fontSize: 'size',
      fontWeight: 'weight'
    }),
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID
  }
})

await finalizeToPng(chart, {
  title: 'Claude Sonnet 5 — the launch-day card',
  subtitle: 'Where each spec ranks across all current models · released 2026-06-30',
  yCaption: 'fuller is more favorable: cheaper for price gauges · larger for capability gauges',
  out: resolve(OUT_DIR, 'spec_card.png')
})
