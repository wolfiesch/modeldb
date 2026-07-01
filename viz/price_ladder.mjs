import * as Plot from '@observablehq/plot'
import { newDocument, finalizeToPng } from './lib/render.mjs'
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
import { PEER_SLUGS, resolvePeers, standardPrice } from './lib/peers.mjs'


function priceLabel(value) {
  const rounded = Math.round(value)
  if (Math.abs(value - rounded) < 0.01) {
    return `$${rounded}`
  }
  return `$${value.toFixed(value < 10 ? 1 : 1).replace(/\.0$/, '')}`
}

const rows = resolvePeers()
  .map((peer) => {
    const input_1m = standardPrice(peer.id, 'input_token')
    const output_1m = standardPrice(peer.id, 'output_token')
    if (input_1m === null || output_1m === null) {
      throw new Error(`Missing standard-tier input/output price for ${peer.canonical_slug}`)
    }
    return {
      ...peer,
      slug: peer.canonical_slug,
      developer: peer.developer_id,
      input_1m,
      output_1m,
      display: shortName(peer.canonical_slug),
      value: priceLabel(output_1m),
      inputLabel: priceLabel(input_1m),
      color: peer.isHero ? HIGHLIGHT : colorFor(peer.developer_id),
      isSonnet: peer.isHero
    }
  })
  .sort((a, b) => b.output_1m - a.output_1m || b.input_1m - a.input_1m)
  .map((row) => ({
    ...row,
    label: row.display
  }))

if (rows.length !== PEER_SLUGS.length) {
  throw new Error(`Expected ${PEER_SLUGS.length} peer rows, got ${rows.length}`)
}

const sonnet = rows.find((row) => row.isSonnet)
if (!sonnet || sonnet.input_1m !== 2 || sonnet.output_1m !== 10) {
  throw new Error('Sonnet 5 launch pricing not present as $2 in / $10 out.')
}

const xMax = Math.ceil((Math.max(...rows.map((row) => row.output_1m)) + 6) / 10) * 10
const yDomain = rows.map((row) => row.label)

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 114,
  marginRight: 310,
  marginBottom: 72,
  marginLeft: 300,
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
      fillOpacity: (row) => (row.isSonnet ? 1 : 0.76),
      insetTop: 17,
      insetBottom: 17,
      rx: 7
    }),
    Plot.dot(rows, {
      x: 'input_1m',
      y: 'label',
      r: (row) => (row.isSonnet ? 7 : 5.5),
      fill: '#ffffff',
      stroke: (row) => row.color,
      strokeWidth: (row) => (row.isSonnet ? 3 : 1.8),
      opacity: (row) => (row.isSonnet ? 1 : 0.5)
    }),
    Plot.text(rows, {
      x: 0,
      y: 'label',
      text: 'display',
      dx: -13,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fill: (row) => (row.isSonnet ? HIGHLIGHT : INK),
      fontSize: (row) => (row.isSonnet ? 24 : 21),
      fontWeight: (row) => (row.isSonnet ? 900 : 650)
    }),
    Plot.text(rows, {
      x: 'output_1m',
      y: 'label',
      text: 'value',
      dx: 12,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: (row) => (row.isSonnet ? HIGHLIGHT : MUTED),
      fontSize: (row) => (row.isSonnet ? 21 : 18),
      fontWeight: (row) => (row.isSonnet ? 900 : 700)
    }),
    Plot.link([sonnet], {
      x1: 'input_1m',
      y1: 'label',
      x2: 'output_1m',
      y2: 'label',
      stroke: HIGHLIGHT,
      strokeOpacity: 0.4,
      strokeWidth: 1.6,
      strokeDasharray: '4 5'
    }),
    Plot.text([sonnet], {
      x: 'output_1m',
      y: 'label',
      text: () => '$2 in / $10 out',
      dx: 82,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: HIGHLIGHT,
      fontSize: 20,
      fontWeight: 900
    }),
    Plot.text([{ x: 1.6, y: rows.at(-1).label }], {
      x: 'x',
      y: 'y',
      text: () => 'open dot = input price',
      dx: 8,
      dy: 34,
      textAnchor: 'start',
      fill: NEUTRAL,
      fontSize: 15,
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
  title: 'Where Sonnet 5 prices in',
  subtitle: 'Output price per 1M tokens · 7 current flagships · standard tier · Sonnet 5: $2 in / $10 out',
  yCaption: 'models.dev standard-tier pricing · n=8',
  out: 'viz/out/price_ladder.png'
})
