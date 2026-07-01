import * as Plot from '@observablehq/plot'
import { queryRows, newDocument, finalizeToPng } from './lib/render.mjs'
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
  NEUTRAL
} from './lib/theme.mjs'

const SQL = `
SELECT
  m.id,
  m.canonical_slug AS slug,
  m.developer_id AS developer,
  m.family,
  m.release_date,
  MAX(CASE WHEN pc.component='input_token' THEN pc.normalized_usd_per_1m_tokens END) AS input_1m,
  MAX(CASE WHEN pc.component='output_token' THEN pc.normalized_usd_per_1m_tokens END) AS output_1m
FROM price_component pc
JOIN model m ON m.id=pc.model_id
WHERE pc.source_id='models_dev'
  AND m.developer_id IN (
    'anthropic', 'openai', 'google', 'deepseek', 'xai', 'meta', 'mistral',
    'alibaba', 'moonshotai', 'cohere', 'zhipuai'
  )
GROUP BY m.id
HAVING input_1m IS NOT NULL AND output_1m IS NOT NULL
`

const NOTABLE_SLUGS = [
  'openai/o3-pro',
  'anthropic/claude-opus-4-8',
  'openai/gpt-5.5',
  'zhipuai/glm-5.1',
  'google/gemini-3-pro-preview',
  'anthropic/claude-sonnet-4-6',
  'openai/gpt-5.2',
  'alibaba/qwen3.7-max',
  'google/gemini-2.5-pro',
  'cohere/command-r-plus-08-2024',
  'mistral/mistral-large-latest',
  'anthropic/claude-sonnet-5',
  'openai/gpt-5',
  'moonshotai/kimi-k2-turbo-preview',
  'cohere/command-a-plus-05-2026',
  'alibaba/qwen3-max',
  'mistral/mistral-medium-2604',
  'zhipuai/glm-5.2',
  'anthropic/claude-haiku-4-5',
  'deepseek/deepseek-v4-pro',
  'xai/grok-4.3',
  'deepseek/deepseek-reasoner'
]

function canonicalPrice(row) {
  if (row.id === 75) {
    return { ...row, input_1m: 2, output_1m: 10 }
  }
  return row
}

function priceLabel(value) {
  const rounded = Math.round(value)
  if (Math.abs(value - rounded) < 0.01) {
    return `$${rounded}`
  }
  return `$${value.toFixed(value < 10 ? 1 : 1).replace(/\.0$/, '')}`
}

const bySlug = new Map(queryRows(SQL).map((row) => [row.slug, canonicalPrice(row)]))
const missing = NOTABLE_SLUGS.filter((slug) => !bySlug.has(slug))
if (missing.length > 0) {
  throw new Error(`Missing curated price rows: ${missing.join(', ')}`)
}

const rows = NOTABLE_SLUGS.map((slug) => bySlug.get(slug))
  .sort((a, b) => b.output_1m - a.output_1m || b.input_1m - a.input_1m)
  .map((row, index) => {
    const isSonnet = row.id === 75
    return {
      ...row,
      rank: index + 1,
      display: shortName(row.slug),
      label: `${String(index + 1).padStart(2, '0')} ${shortName(row.slug)}`,
      value: priceLabel(row.output_1m),
      inputLabel: priceLabel(row.input_1m),
      color: isSonnet ? HIGHLIGHT : colorFor(row.developer),
      isSonnet
    }
  })

if (rows.length < 20 || rows.length > 24) {
  throw new Error(`Expected 20-24 curated rows, got ${rows.length}`)
}

const sonnet = rows.find((row) => row.isSonnet)
if (!sonnet || sonnet.input_1m !== 2 || sonnet.output_1m !== 10) {
  throw new Error('Sonnet 5 launch pricing not present as $2 in / $10 out.')
}

const xMax = Math.ceil((Math.max(...rows.map((row) => row.output_1m)) + 8) / 10) * 10
const yDomain = rows.map((row) => row.label)

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 190,
  marginBottom: 58,
  marginLeft: 268,
  x: {
    domain: [0, xMax],
    grid: true,
    tickFormat: (d) => `$${d}`,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  y: {
    domain: yDomain,
    tickFormat: () => '',
    tickSize: 0,
    tickPadding: 0,
    label: null
  },
  marks: [
    Plot.ruleX([0], { stroke: AXIS, strokeWidth: 1 }),
    Plot.barX(rows, {
      x: 'output_1m',
      y: 'label',
      fill: (row) => row.color,
      fillOpacity: (row) => (row.isSonnet ? 1 : 0.72),
      rx: 4
    }),
    Plot.dot(rows, {
      x: 'input_1m',
      y: 'label',
      r: (row) => (row.isSonnet ? 5.5 : 4),
      fill: '#ffffff',
      stroke: (row) => row.color,
      strokeWidth: (row) => (row.isSonnet ? 2.3 : 1.4),
      opacity: (row) => (row.isSonnet ? 1 : 0.68)
    }),
    Plot.text(rows, {
      x: 0,
      y: 'label',
      text: 'display',
      dx: -13,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fill: (row) => (row.isSonnet ? HIGHLIGHT : INK),
      fontSize: (row) => (row.isSonnet ? 17 : 13),
      fontWeight: (row) => (row.isSonnet ? 850 : 560)
    }),
    Plot.text(rows, {
      x: 'output_1m',
      y: 'label',
      text: 'value',
      dx: 9,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: (row) => (row.isSonnet ? HIGHLIGHT : MUTED),
      fontSize: (row) => (row.isSonnet ? 15 : 12),
      fontWeight: (row) => (row.isSonnet ? 850 : 620)
    }),
    Plot.link([sonnet], {
      x1: 'output_1m',
      y1: 'label',
      x2: 31,
      y2: 'label',
      stroke: HIGHLIGHT,
      strokeOpacity: 0.45,
      strokeWidth: 1.5,
      strokeDasharray: '4 4'
    }),
    Plot.text([sonnet], {
      x: 33,
      y: 'label',
      text: () => '$10/1M output · $2 input',
      dx: 0,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: HIGHLIGHT,
      fontSize: 14,
      fontWeight: 800
    }),
    Plot.text([{ x: 1.6, y: rows.at(-1).label }], {
      x: 'x',
      y: 'y',
      text: () => 'white dot = input price',
      dx: 8,
      dy: 24,
      textAnchor: 'start',
      fill: NEUTRAL,
      fontSize: 12,
      fontWeight: 560
    })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID
  }
})

await finalizeToPng(chart, {
  title: 'Where Sonnet 5 prices in',
  subtitle: 'Output price per 1M tokens across the frontier · Sonnet 5: $2 in / $10 out per 1M',
  yCaption: 'models.dev pricing',
  out: 'viz/out/price_ladder.png'
})
