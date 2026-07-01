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
  FAINT,
  NEUTRAL
} from './lib/theme.mjs'

const SQL = `
SELECT
  m.id AS id,
  m.canonical_slug AS slug,
  m.developer_id AS developer,
  MAX(CASE WHEN pc.component='input_token' THEN pc.normalized_usd_per_1m_tokens END) AS input_1m,
  MAX(CASE WHEN pc.component='cache_read' THEN pc.normalized_usd_per_1m_tokens END) AS cache_read_1m,
  MAX(CASE WHEN pc.component='output_token' THEN pc.normalized_usd_per_1m_tokens END) AS output_1m
FROM price_component pc
JOIN model m ON m.id=pc.model_id
WHERE pc.source_id='models_dev'
GROUP BY m.id
HAVING input_1m IS NOT NULL AND cache_read_1m IS NOT NULL
`

const SONNET_5_ID = 75
const CACHE_HIT_RATE = 0.9
const FRESH_RATE = 1 - CACHE_HIT_RATE
const SONNET_5_LAUNCH_PRICING = {
  input_1m: 2,
  cache_read_1m: 0.2,
  output_1m: 10
}

const CURATED_SLUGS = new Set([
  'alibaba/qwen3-coder-480b-a35b-instruct',
  'moonshotai/kimi-k2-0905-preview',
  'alibaba/qwen3-235b-a22b',
  'openai/gpt-5',
  'deepseek/deepseek-chat',
  'xai/grok-4.20-0309-reasoning',
  'moonshotai/kimi-k2.6',
  'openai/gpt-5.2',
  'openai/o4-mini',
  'anthropic/claude-sonnet-5',
  'xai/grok-4.3',
  'google/gemini-2.5-pro',
  'anthropic/claude-3-7-sonnet-20250219',
  'anthropic/claude-sonnet-4-20250514',
  'openai/gpt-4.1',
  'openai/gpt-5.4',
  'anthropic/claude-opus-4-5',
  'openai/o3',
  'anthropic/claude-opus-4-1'
])

function dollars(value) {
  if (value < 1) {
    return `$${value.toFixed(2)}`
  }
  if (value < 10) {
    return `$${value.toFixed(value % 1 === 0 ? 0 : 1)}`
  }
  return `$${value.toFixed(0)}`
}

function normalizePricing(row) {
  if (row.id === SONNET_5_ID) {
    return { ...row, ...SONNET_5_LAUNCH_PRICING }
  }
  return row
}

const rows = queryRows(SQL)
  .map((row) => ({
    id: Number(row.id),
    slug: row.slug,
    developer: row.developer,
    input_1m: Number(row.input_1m),
    cache_read_1m: Number(row.cache_read_1m),
    output_1m: Number(row.output_1m)
  }))
  .map(normalizePricing)
  .filter(
    (row) =>
      CURATED_SLUGS.has(row.slug) &&
      Number.isFinite(row.input_1m) &&
      Number.isFinite(row.cache_read_1m) &&
      row.input_1m > 0 &&
      row.cache_read_1m > 0
  )
  .map((row) => {
    const effective = CACHE_HIT_RATE * row.cache_read_1m + FRESH_RATE * row.input_1m
    const discount = 1 - effective / row.input_1m
    const isSonnet5 = row.id === SONNET_5_ID
    return {
      ...row,
      effective,
      discount,
      label: shortName(row.slug),
      color: isSonnet5 ? HIGHLIGHT : colorFor(row.developer),
      isSonnet5
    }
  })
  .sort((a, b) => a.effective - b.effective || a.input_1m - b.input_1m)

if (rows.length < 15) {
  throw new Error(`Expected at least 15 curated cache-price rows; found ${rows.length}.`)
}
if (!rows.some((row) => row.isSonnet5)) {
  throw new Error('Sonnet 5 missing from cache economics chart.')
}

const domain = rows.map((row) => row.label)
const allPrices = rows.flatMap((row) => [row.effective, row.input_1m])
const xMin = Math.max(0.01, Math.min(...allPrices) * 0.72)
const xMax = Math.max(...allPrices) * 1.28
const ticks = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].filter(
  (tick) => tick >= xMin && tick <= xMax
)
const sonnet5 = rows.find((row) => row.isSonnet5)

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 150,
  marginRight: 188,
  marginBottom: 78,
  marginLeft: 280,
  x: {
    type: 'log',
    domain: [xMin, xMax],
    ticks,
    tickFormat: dollars,
    tickSize: 0,
    tickPadding: 10,
    grid: true,
    label: '$ per 1M input tokens',
    labelAnchor: 'center',
    labelOffset: 48
  },
  y: {
    domain,
    axis: null,
    padding: 0.33,
    label: null
  },
  marks: [
    Plot.ruleX(ticks, { stroke: GRID, strokeWidth: 1 }),
    Plot.link(rows, {
      x1: 'effective',
      x2: 'input_1m',
      y1: 'label',
      y2: 'label',
      stroke: (row) => row.color,
      strokeOpacity: (row) => (row.isSonnet5 ? 0.76 : 0.42),
      strokeWidth: (row) => (row.isSonnet5 ? 5 : 3.2),
      strokeLinecap: 'round'
    }),
    Plot.dot(rows, {
      x: 'input_1m',
      y: 'label',
      r: (row) => (row.isSonnet5 ? 7.5 : 5.7),
      fill: '#ffffff',
      stroke: NEUTRAL,
      strokeOpacity: 0.72,
      strokeWidth: (row) => (row.isSonnet5 ? 2.1 : 1.4)
    }),
    Plot.dot(rows, {
      x: 'effective',
      y: 'label',
      r: (row) => (row.isSonnet5 ? 9.5 : 7),
      fill: (row) => row.color,
      fillOpacity: (row) => (row.isSonnet5 ? 1 : 0.88),
      stroke: (row) => (row.isSonnet5 ? INK : '#ffffff'),
      strokeWidth: (row) => (row.isSonnet5 ? 1.8 : 1.2)
    }),
    Plot.text(rows, {
      x: xMin,
      y: 'label',
      text: 'label',
      dx: -14,
      fill: (row) => (row.isSonnet5 ? HIGHLIGHT : INK),
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isSonnet5 ? 18 : 15),
      fontWeight: (row) => (row.isSonnet5 ? 780 : 560)
    }),
    Plot.text(rows, {
      x: 'effective',
      y: 'label',
      text: (row) => dollars(row.effective),
      dx: -10,
      fill: (row) => (row.isSonnet5 ? HIGHLIGHT : MUTED),
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isSonnet5 ? 14 : 12),
      fontWeight: (row) => (row.isSonnet5 ? 780 : 560)
    }),
    Plot.text(rows, {
      x: 'input_1m',
      y: 'label',
      text: (row) => dollars(row.input_1m),
      dx: 10,
      fill: (row) => (row.isSonnet5 ? INK : FAINT),
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isSonnet5 ? 14 : 12),
      fontWeight: (row) => (row.isSonnet5 ? 720 : 520)
    }),
    Plot.text([sonnet5], {
      x: 'input_1m',
      y: 'label',
      text: (row) => `${Math.round(row.discount * 100)}% cheaper with cache`,
      dx: 70,
      fill: HIGHLIGHT,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: 16,
      fontWeight: 800
    }),
    Plot.text([{ x: 0.056, y: domain[0], text: 'effective\n90% cached' }], {
      x: 'x',
      y: 'y',
      text: 'text',
      dy: -24,
      fill: MUTED,
      textAnchor: 'middle',
      lineAnchor: 'bottom',
      fontSize: 13,
      fontWeight: 650
    }),
    Plot.text([{ x: 12, y: domain[0], text: 'sticker\nfresh input' }], {
      x: 'x',
      y: 'y',
      text: 'text',
      dy: -24,
      fill: FAINT,
      textAnchor: 'middle',
      lineAnchor: 'bottom',
      fontSize: 13,
      fontWeight: 650
    }),
    Plot.ruleY([domain[0]], { stroke: AXIS, strokeOpacity: 0.55 })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID
  }
})

await finalizeToPng(chart, {
  title: 'The prompt-caching discount',
  subtitle:
    'Sticker vs effective input price at 90% cache hit · Anthropic prices cache reads at $0.20/1M',
  yCaption: 'models.dev pricing',
  out: resolve(OUT_DIR, 'cache_economics.png')
})
