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

const TARGET = 'anthropic/claude-sonnet-5'
const PEER_DEVELOPER = 'anthropic'
const INTRO_PRICE = new Map([[TARGET, { out: 10, through: '2026-08-31' }]])

const rows = queryRows(`
SELECT m.canonical_slug AS slug,
       m.developer_id AS developer,
       MAX(CASE WHEN pc.component='input_token' THEN pc.normalized_usd_per_1m_tokens END) AS in_1m,
       MAX(CASE WHEN pc.component='output_token' THEN pc.normalized_usd_per_1m_tokens END) AS out_1m,
       MAX(CASE WHEN cap.capability='context_window' THEN cap.value END) AS ctx
FROM model m
LEFT JOIN price_component pc ON pc.model_id=m.id AND pc.source_id='models_dev'
LEFT JOIN model_capability cap ON cap.model_id=m.id
WHERE m.developer_id='anthropic'
GROUP BY m.id
`)

const points = rows
  .filter((row) => row.out_1m != null)
  .map((row) => ({
    slug: row.slug,
    developer: row.developer ?? PEER_DEVELOPER,
    output_1m: Number(row.out_1m),
    context: row.ctx ? Number(row.ctx) : null,
    isTarget: row.slug === TARGET
  }))
  .sort((a, b) => a.output_1m - b.output_1m || a.slug.localeCompare(b.slug))

if (!points.some((point) => point.isTarget)) {
  throw new Error(`${TARGET} not found with standard output pricing.`)
}

const formatPrice = (value) => {
  const rounded = Math.round(value)
  if (Math.abs(value - rounded) < 0.005) {
    return `$${rounded}`
  }
  return `$${value.toFixed(2).replace(/0+$/, '').replace(/\.$/, '')}`
}

const formatContext = (value) => (value ? `${Math.round(value / 1_000)}K ctx` : null)

const labelFor = (point) => {
  const context = formatContext(point.context)
  const intro = INTRO_PRICE.get(point.slug)
  if (point.isTarget && intro) {
    return `${formatPrice(intro.out)}→${formatPrice(point.output_1m)}/1M${context ? ` · ${context}` : ''}`
  }
  return `${formatPrice(point.output_1m)}/1M`
}

const yDomain = points.map((point) => point.slug)
const maxOutput = Math.max(...points.map((point) => point.output_1m))
const anthropic = colorFor(PEER_DEVELOPER)

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 160,
  marginBottom: 56,
  marginLeft: 180,
  style: plotStyle,
  x: {
    axis: null,
    domain: [0, maxOutput * 1.04],
    grid: true,
    label: null
  },
  y: {
    axis: null,
    domain: yDomain,
    label: null,
    padding: 0.22
  },
  marks: [
    Plot.gridX({ stroke: GRID, strokeOpacity: 0.85 }),
    Plot.axisX({
      anchor: 'bottom',
      tickSize: 0,
      tickFormat: (value) => `${formatPrice(value)}`,
      label: null,
      color: AXIS
    }),
    Plot.axisY({
      tickSize: 0,
      tickFormat: shortName,
      label: null,
      color: NEUTRAL,
      fontSize: 12
    }),
    Plot.barX(points, {
      y: 'slug',
      x: 'output_1m',
      fill: (point) => (point.isTarget ? HIGHLIGHT : '#c6dbef'),
      stroke: (point) => (point.isTarget ? 'black' : anthropic),
      strokeWidth: (point) => (point.isTarget ? 1.6 : 0.6),
      strokeOpacity: (point) => (point.isTarget ? 1 : 0.3)
    }),
    Plot.text(points, {
      y: 'slug',
      x: 'output_1m',
      text: labelFor,
      dx: 8,
      textAnchor: 'start',
      fill: (point) => (point.isTarget ? '#101827' : NEUTRAL),
      fontSize: 11,
      fontWeight: (point) => (point.isTarget ? 760 : 430)
    })
  ]
})

const out = resolve(OUT_DIR, 'landing_anthropic_claude-sonnet-5.png')
await finalizeToPng(chart, {
  title: 'Where does Claude Sonnet 5 land?',
  subtitle:
    'Anthropic output-price ladder · Sonnet 5: $10/1M intro through 2026-08-31, $15 standard after · Source: models.dev',
  yCaption: 'standard output price — USD per 1M tokens',
  out
})
