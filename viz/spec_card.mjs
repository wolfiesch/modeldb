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
  INK,
  MUTED,
  FAINT,
  GRID,
  AXIS,
  NEUTRAL
} from './lib/theme.mjs'
import { resolvePeers, standardPrice } from './lib/peers.mjs'

const peers = resolvePeers()
const CAPABILITY_SQL = `
SELECT
  model_id,
  capability,
  MAX(CAST(value AS INTEGER)) AS value
FROM model_capability
WHERE capability IN ('context_window', 'max_output')
  AND model_id IN (${peers.map(() => '?').join(',')})
GROUP BY model_id, capability
`

const capabilityRows = queryRows(CAPABILITY_SQL, peers.map((peer) => peer.id))
const capabilityByModel = new Map()
for (const row of capabilityRows) {
  const caps = capabilityByModel.get(row.model_id) ?? {}
  caps[row.capability] = Number(row.value)
  capabilityByModel.set(row.model_id, caps)
}

function requireNumber(value, label) {
  const number = Number(value)
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`Missing positive value for ${label}.`)
  }
  return number
}

function trimDecimal(value) {
  return value.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '')
}

function priceLabel(value) {
  const number = Number(value)
  if (Number.isInteger(number)) {
    return `$${number}`
  }
  if (number < 0.01) {
    return `$${trimDecimal(number.toFixed(4))}`
  }
  if (number < 1) {
    return `$${Number.isInteger(number * 100) ? number.toFixed(2) : trimDecimal(number.toFixed(3))}`
  }
  return `$${trimDecimal(number.toFixed(3))}`
}

function compactTokens(value) {
  const number = Number(value)
  if (number >= 1_000_000) {
    if (number % 1_000 === 0) {
      return `${(number / 1_000_000).toFixed(2).replace(/\.00$/, '').replace(/0$/, '')}M`
    }
    return `${(number / 1_048_576).toFixed(2).replace(/\.00$/, '').replace(/0$/, '')}M`
  }
  if (number % 1_000 === 0) {
    return `${Math.round(number / 1_000)}K`
  }
  return `${Math.round(number / 1_024)}K`
}

const modelRows = peers.map((peer) => {
  const caps = capabilityByModel.get(peer.id) ?? {}
  return {
    id: peer.id,
    slug: peer.canonical_slug,
    developer: peer.developer_id,
    label: shortName(peer.canonical_slug),
    isHero: peer.isHero,
    inputPrice: requireNumber(standardPrice(peer.id, 'input_token'), `${peer.canonical_slug} input price`),
    outputPrice: requireNumber(standardPrice(peer.id, 'output_token'), `${peer.canonical_slug} output price`),
    cacheReadPrice: requireNumber(standardPrice(peer.id, 'cache_read'), `${peer.canonical_slug} cache-read price`),
    contextWindow: requireNumber(caps.context_window, `${peer.canonical_slug} context window`),
    maxOutput: requireNumber(caps.max_output, `${peer.canonical_slug} max output`)
  }
})

if (modelRows.length !== peers.length) {
  throw new Error(`Expected ${peers.length} peer models, got ${modelRows.length}.`)
}

const metrics = [
  {
    id: 'inputPrice',
    title: 'Input $/1M',
    caption: 'lower is better',
    format: priceLabel,
    better: 'lower'
  },
  {
    id: 'outputPrice',
    title: 'Output $/1M',
    caption: 'lower is better',
    format: priceLabel,
    better: 'lower'
  },
  {
    id: 'cacheReadPrice',
    title: 'Cache-read $/1M',
    caption: 'lower is better',
    format: priceLabel,
    better: 'lower'
  },
  {
    id: 'contextWindow',
    title: 'Context window',
    caption: 'higher is better',
    format: compactTokens,
    better: 'higher'
  },
  {
    id: 'maxOutput',
    title: 'Max output',
    caption: 'higher is better',
    format: compactTokens,
    better: 'higher'
  }
]

const panelGeometry = [
  { x: 72, y: 132 },
  { x: 566, y: 132 },
  { x: 1060, y: 132 },
  { x: 72, y: 512 },
  { x: 566, y: 512 }
]
const PANEL_WIDTH = 468
const PANEL_HEIGHT = 316
const LABEL_WIDTH = 142
const BAR_START_OFFSET = 154
const BAR_WIDTH = 232
const BAR_HEIGHT = 18
const ROW_GAP = 31
const FIRST_ROW_Y = 78

function sortRows(metric) {
  const direction = metric.better === 'lower' ? 1 : -1
  return [...modelRows].sort(
    (a, b) => direction * (a[metric.id] - b[metric.id]) || a.label.localeCompare(b.label)
  )
}

const panels = metrics.map((metric, index) => {
  const origin = panelGeometry[index]
  const rows = sortRows(metric)
  const max = Math.max(...rows.map((row) => row[metric.id]))
  return { ...metric, ...origin, rows, max }
})

const frames = panels.map((panel) => ({
  x1: panel.x,
  x2: panel.x + PANEL_WIDTH,
  y1: panel.y,
  y2: panel.y + PANEL_HEIGHT
}))

const panelTitles = panels.flatMap((panel) => [
  {
    x: panel.x + 22,
    y: panel.y + 34,
    text: panel.title,
    fill: INK,
    size: 22,
    weight: 820
  },
  {
    x: panel.x + 22,
    y: panel.y + 58,
    text: panel.caption,
    fill: panel.better === 'lower' ? MUTED : NEUTRAL,
    size: 13,
    weight: 620
  }
])

const bars = panels.flatMap((panel) =>
  panel.rows.map((row, index) => {
    const y = panel.y + FIRST_ROW_Y + index * ROW_GAP
    const value = row[panel.id]
    const width = Math.max(2, value / panel.max * BAR_WIDTH)
    return {
      panel: panel.id,
      label: row.label,
      valueLabel: panel.format(value),
      rawValue: value,
      x1: panel.x + BAR_START_OFFSET,
      x2: panel.x + BAR_START_OFFSET + width,
      y1: y - BAR_HEIGHT / 2,
      y2: y + BAR_HEIGHT / 2,
      y,
      labelX: panel.x + LABEL_WIDTH,
      valueX: Math.min(panel.x + PANEL_WIDTH - 18, panel.x + BAR_START_OFFSET + width + 9),
      color: row.isHero ? HIGHLIGHT : colorFor(row.developer),
      textFill: row.isHero ? HIGHLIGHT : INK,
      valueFill: row.isHero ? HIGHLIGHT : MUTED,
      opacity: row.isHero ? 1 : 0.76,
      isHero: row.isHero
    }
  })
)

const LAST_ROW_OFFSET = (modelRows.length - 1) * ROW_GAP
const gridlines = panels.flatMap((panel) => [
  {
    x1: panel.x + BAR_START_OFFSET,
    x2: panel.x + BAR_START_OFFSET,
    y1: panel.y + FIRST_ROW_Y - 20,
    y2: panel.y + FIRST_ROW_Y + LAST_ROW_OFFSET + 20
  },
  {
    x1: panel.x + BAR_START_OFFSET + BAR_WIDTH,
    x2: panel.x + BAR_START_OFFSET + BAR_WIDTH,
    y1: panel.y + FIRST_ROW_Y - 20,
    y2: panel.y + FIRST_ROW_Y + LAST_ROW_OFFSET + 20
  }
])

const legendX = 1060
const legendY = 512
const legendRows = [
  { text: 'Direct peer cohort', y: legendY + 36, fill: INK, size: 23, weight: 820 },
  { text: 'Panel scales are independent.', y: legendY + 76, fill: MUTED, size: 15, weight: 540 },
  { text: 'Compare bar lengths only within the same metric.', y: legendY + 102, fill: MUTED, size: 15, weight: 540 },
  { text: 'Best-to-worst: cheapest prices, largest token limits.', y: legendY + 130, fill: MUTED, size: 15, weight: 540 },
  { text: 'Sonnet 5 standard tier: $2 input · $10 output · $0.20 cache read.', y: legendY + 174, fill: HIGHLIGHT, size: 16, weight: 760 },
  { text: 'Source: models.dev pricing + model capability catalog.', y: legendY + 224, fill: FAINT, size: 13, weight: 560 }
]

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 0,
  marginRight: 0,
  marginBottom: 0,
  marginLeft: 0,
  x: { domain: [0, WIDTH], axis: null, label: null },
  y: { domain: [HEIGHT, 0], axis: null, label: null },
  marks: [
    Plot.rect(frames, {
      x1: 'x1',
      x2: 'x2',
      y1: 'y1',
      y2: 'y2',
      fill: '#ffffff',
      stroke: AXIS,
      strokeOpacity: 0.78,
      strokeWidth: 1.2,
      rx: 22
    }),
    Plot.ruleX(gridlines, {
      x: 'x1',
      y1: 'y1',
      y2: 'y2',
      stroke: GRID,
      strokeWidth: 1,
      strokeOpacity: 0.85
    }),
    Plot.ruleX(gridlines, {
      x: 'x2',
      y1: 'y1',
      y2: 'y2',
      stroke: GRID,
      strokeWidth: 1,
      strokeOpacity: 0.5
    }),
    Plot.text(panelTitles, {
      x: 'x',
      y: 'y',
      text: 'text',
      fill: 'fill',
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: 'size',
      fontWeight: 'weight'
    }),
    Plot.rect(bars, {
      x1: 'x1',
      x2: 'x2',
      y1: 'y1',
      y2: 'y2',
      fill: 'color',
      fillOpacity: 'opacity',
      rx: 5
    }),
    Plot.text(bars, {
      x: 'labelX',
      y: 'y',
      text: 'label',
      fill: 'textFill',
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isHero ? 14.5 : 13),
      fontWeight: (row) => (row.isHero ? 860 : 600)
    }),
    Plot.text(bars, {
      x: 'valueX',
      y: 'y',
      text: 'valueLabel',
      fill: 'valueFill',
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isHero ? 14 : 12.5),
      fontWeight: (row) => (row.isHero ? 860 : 620)
    }),
    Plot.rect([{ x1: legendX, x2: legendX + PANEL_WIDTH, y1: legendY, y2: legendY + PANEL_HEIGHT }], {
      x1: 'x1',
      x2: 'x2',
      y1: 'y1',
      y2: 'y2',
      fill: '#fbfcfe',
      stroke: GRID,
      strokeWidth: 1,
      rx: 22
    }),
    Plot.dot([{ x: legendX + 28, y: legendY + 146 }], {
      x: 'x',
      y: 'y',
      r: 8,
      fill: HIGHLIGHT,
      stroke: '#ffffff',
      strokeWidth: 2
    }),
    Plot.text(legendRows, {
      x: legendX + 52,
      y: 'y',
      text: 'text',
      fill: 'fill',
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: 'size',
      fontWeight: 'weight'
    })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID
  }
})

await finalizeToPng(chart, {
  title: 'Sonnet 5 vs the flagships',
  subtitle: 'Head-to-head with 7 hand-picked current flagships · standard-tier pricing · n=8',
  yCaption: 'Five direct spec comparisons; bars are normalized within each panel.',
  out: resolve(OUT_DIR, 'spec_card.png')
})
