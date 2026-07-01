import * as Plot from '@observablehq/plot'
import { resolve } from 'node:path'
import { newDocument, finalizeToPng, OUT_DIR } from './lib/render.mjs'
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
import { PEER_SLUGS, resolvePeers, standardPrice } from './lib/peers.mjs'

const CACHE_HIT_RATE = 0.9
const FRESH_RATE = 1 - CACHE_HIT_RATE

function dollars(value) {
  if (value < 1) {
    return `$${value.toFixed(2)}`
  }
  if (value < 10) {
    return `$${value.toFixed(value % 1 === 0 ? 0 : 1)}`
  }
  return `$${value.toFixed(0)}`
}

function priceFor(modelId, component) {
  const value = standardPrice(modelId, component)
  return value === null ? null : Number(value)
}

const rows = resolvePeers()
  .map((peer) => {
    const input_1m = priceFor(peer.id, 'input_token')
    const cache_read_1m = priceFor(peer.id, 'cache_read')
    if (
      !Number.isFinite(input_1m) ||
      !Number.isFinite(cache_read_1m) ||
      input_1m <= 0 ||
      cache_read_1m <= 0
    ) {
      throw new Error(`Missing standard cache pricing for ${peer.canonical_slug}.`)
    }
    const effective = CACHE_HIT_RATE * cache_read_1m + FRESH_RATE * input_1m
    const discount = 1 - effective / input_1m
    return {
      id: Number(peer.id),
      slug: peer.canonical_slug,
      developer: peer.developer_id,
      input_1m,
      cache_read_1m,
      effective,
      discount,
      discountLabel: `-${Math.round(discount * 100)}%`,
      label: shortName(peer.canonical_slug),
      labelX: Math.sqrt(effective * input_1m),
      color: peer.isHero ? HIGHLIGHT : colorFor(peer.developer_id),
      isHero: peer.isHero
    }
  })
  .sort((a, b) => a.effective - b.effective || a.input_1m - b.input_1m)

if (rows.length !== PEER_SLUGS.length) {
  throw new Error(`Expected ${PEER_SLUGS.length} curated peer cache-price rows; found ${rows.length}.`)
}
if (!rows.some((row) => row.isHero)) {
  throw new Error('Sonnet 5 missing from cache economics chart.')
}

const domain = rows.map((row) => row.label)
const allPrices = rows.flatMap((row) => [row.effective, row.input_1m])
const xMin = Math.max(0.01, Math.min(...allPrices) * 0.72)
const xMax = Math.max(...allPrices) * 1.28
const ticks = [0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50].filter(
  (tick) => tick >= xMin && tick <= xMax
)

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
      strokeOpacity: (row) => (row.isHero ? 0.78 : 0.46),
      strokeWidth: (row) => (row.isHero ? 5.5 : 3.6),
      strokeLinecap: 'round'
    }),
    Plot.dot(rows, {
      x: 'input_1m',
      y: 'label',
      r: (row) => (row.isHero ? 7.8 : 6.1),
      fill: '#ffffff',
      stroke: FAINT,
      strokeOpacity: (row) => (row.isHero ? 0.9 : 0.68),
      strokeWidth: (row) => (row.isHero ? 2.2 : 1.5)
    }),
    Plot.dot(rows, {
      x: 'effective',
      y: 'label',
      r: (row) => (row.isHero ? 10 : 7.6),
      fill: (row) => row.color,
      fillOpacity: (row) => (row.isHero ? 1 : 0.92),
      stroke: (row) => (row.isHero ? INK : '#ffffff'),
      strokeWidth: (row) => (row.isHero ? 1.9 : 1.25)
    }),
    Plot.text(rows, {
      x: xMin,
      y: 'label',
      text: 'label',
      dx: -14,
      fill: (row) => (row.isHero ? HIGHLIGHT : INK),
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isHero ? 22 : 18),
      fontWeight: (row) => (row.isHero ? 820 : 620)
    }),
    Plot.text(rows, {
      x: 'effective',
      y: 'label',
      text: (row) => dollars(row.effective),
      dx: -10,
      fill: (row) => (row.isHero ? HIGHLIGHT : MUTED),
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isHero ? 16 : 14),
      fontWeight: (row) => (row.isHero ? 780 : 560)
    }),
    Plot.text(rows, {
      x: 'input_1m',
      y: 'label',
      text: (row) => dollars(row.input_1m),
      dx: 10,
      fill: (row) => (row.isHero ? INK : FAINT),
      textAnchor: 'start',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isHero ? 16 : 14),
      fontWeight: (row) => (row.isHero ? 740 : 520)
    }),
    Plot.text(rows, {
      x: 'labelX',
      y: 'label',
      text: 'discountLabel',
      fill: (row) => (row.isHero ? HIGHLIGHT : row.color),
      textAnchor: 'middle',
      lineAnchor: 'middle',
      fontSize: (row) => (row.isHero ? 16 : 14),
      fontWeight: (row) => (row.isHero ? 820 : 720)
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
  subtitle: 'Sticker vs effective input at 90% cache hit · 7 flagships · standard tier · n=8',
  yCaption: 'models.dev standard-tier pricing',
  out: resolve(OUT_DIR, 'cache_economics.png')
})
