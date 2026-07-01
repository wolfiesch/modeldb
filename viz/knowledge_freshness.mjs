import * as Plot from '@observablehq/plot'
import { resolve } from 'node:path'
import { queryRows, newDocument, finalizeToPng, OUT_DIR } from './lib/render.mjs'
import {
  WIDTH,
  HEIGHT,
  MS_PER_DAY,
  colorFor,
  shortName,
  plotStyle,
  HIGHLIGHT,
  MUTED,
  GRID,
  AXIS,
  INK
} from './lib/theme.mjs'

const SONNET_5 = 'anthropic/claude-sonnet-5'
const MAJOR_DEVELOPERS = new Set([
  'anthropic',
  'openai',
  'google',
  'xai',
  'deepseek',
  'meta',
  'mistral',
  'cohere',
  'alibaba',
  'moonshotai',
  'zhipuai'
])
const EXCLUDED_VARIANTS = /(?:highspeed|customtools|spark|labs-|latest)/i

const SQL = `
SELECT
  m.canonical_slug AS slug,
  m.developer_id AS developer,
  m.knowledge_cutoff AS knowledge_cutoff,
  m.release_date AS release_date
FROM model m
WHERE m.knowledge_cutoff IS NOT NULL
  AND m.release_date IS NOT NULL
  AND m.release_date >= '2025-06-01'
ORDER BY m.release_date DESC, m.canonical_slug
`

function parseDate(value, { endOfMonth = false } = {}) {
  const text = String(value).trim()
  const match = text.match(/^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$/)
  if (!match) {
    return new Date(text)
  }

  const year = Number(match[1])
  const month = match[2] ? Number(match[2]) - 1 : endOfMonth ? 11 : 0
  if (match[3]) {
    return new Date(Date.UTC(year, month, Number(match[3])))
  }
  if (endOfMonth) {
    return new Date(Date.UTC(year, month + 1, 0))
  }
  return new Date(Date.UTC(year, month, 1))
}

function formatMonth(date) {
  return date.toLocaleDateString('en-US', {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC'
  })
}

function formatGap(months) {
  return months < 1 ? `${Math.round(months * 30)}d` : `${months.toFixed(1)} mo`
}

function toPoint(row) {
  const cutoff = parseDate(row.knowledge_cutoff, { endOfMonth: true })
  const release = parseDate(row.release_date)
  const gapDays = (release - cutoff) / MS_PER_DAY
  const gapMonths = gapDays / 30.44
  const isSonnet = row.slug === SONNET_5

  return {
    ...row,
    cutoff,
    release,
    gapDays,
    gapMonths,
    isSonnet,
    label: isSonnet ? 'Sonnet 5' : shortName(row.slug),
    gapLabel: formatGap(gapMonths),
    color: isSonnet ? HIGHLIGHT : colorFor(row.developer)
  }
}

const rows = queryRows(SQL)
  .filter((row) => MAJOR_DEVELOPERS.has(String(row.developer).toLowerCase()))
  .filter((row) => row.slug === SONNET_5 || !EXCLUDED_VARIANTS.test(row.slug))
  .map(toPoint)
  .filter((row) => Number.isFinite(row.gapMonths) && row.gapDays >= 0)
  .sort((a, b) => b.release - a.release || a.gapMonths - b.gapMonths || a.label.localeCompare(b.label))

const sonnet = rows.find((row) => row.isSonnet)
if (!sonnet) {
  throw new Error('Sonnet 5 knowledge freshness row missing from model table.')
}

const chartRows = rows.slice(0, 28)
if (!chartRows.some((row) => row.isSonnet)) {
  chartRows.unshift(sonnet)
}
if (chartRows.length < 20) {
  throw new Error(`Expected at least 20 recent knowledge-cutoff rows; got ${chartRows.length}.`)
}

const orderedRows = chartRows.sort(
  (a, b) => b.release - a.release || a.gapMonths - b.gapMonths || a.label.localeCompare(b.label)
)
const yDomain = orderedRows.map((row) => row.label)
const minCutoff = new Date(Math.min(...orderedRows.map((row) => row.cutoff.getTime())) - 18 * MS_PER_DAY)
const maxRelease = new Date(Math.max(...orderedRows.map((row) => row.release.getTime())) + 120 * MS_PER_DAY)
const callouts = [
  {
    x: sonnet.release,
    y: sonnet.label,
    text: `Sonnet 5: ${formatGap(sonnet.gapMonths)} gap · ${formatMonth(sonnet.cutoff)} → Jun 30, 2026`,
    color: HIGHLIGHT
  }
]

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 132,
  marginRight: 280,
  marginBottom: 88,
  marginLeft: 220,
  x: {
    domain: [minCutoff, maxRelease],
    grid: true,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  y: {
    domain: yDomain,
    tickSize: 0,
    tickPadding: 8,
    label: null
  },
  marks: [
    Plot.ruleY(yDomain, { stroke: GRID, strokeWidth: 0.7, strokeOpacity: 0.56 }),
    Plot.ruleX([sonnet.release], {
      stroke: HIGHLIGHT,
      strokeWidth: 1.3,
      strokeOpacity: 0.36,
      strokeDasharray: '4 5'
    }),
    Plot.link(
      orderedRows.filter((row) => !row.isSonnet),
      {
        x1: 'cutoff',
        x2: 'release',
        y1: 'label',
        y2: 'label',
        stroke: (row) => row.color,
        strokeWidth: 5,
        strokeOpacity: 0.48,
        strokeLinecap: 'round'
      }
    ),
    Plot.link(
      orderedRows.filter((row) => row.isSonnet),
      {
        x1: 'cutoff',
        x2: 'release',
        y1: 'label',
        y2: 'label',
        stroke: HIGHLIGHT,
        strokeWidth: 11,
        strokeOpacity: 0.96,
        strokeLinecap: 'round'
      }
    ),
    Plot.dot(orderedRows, {
      x: 'cutoff',
      y: 'label',
      r: (row) => (row.isSonnet ? 5 : 3.4),
      fill: '#ffffff',
      stroke: (row) => row.color,
      strokeWidth: (row) => (row.isSonnet ? 2.4 : 1.2)
    }),
    Plot.dot(orderedRows, {
      x: 'release',
      y: 'label',
      r: (row) => (row.isSonnet ? 8 : 4.8),
      fill: (row) => row.color,
      fillOpacity: (row) => (row.isSonnet ? 1 : 0.88),
      stroke: '#ffffff',
      strokeWidth: (row) => (row.isSonnet ? 2.4 : 1.2)
    }),
    Plot.text(orderedRows, {
      x: 'release',
      y: 'label',
      text: 'gapLabel',
      dx: 10,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: (row) => (row.isSonnet ? HIGHLIGHT : MUTED),
      fontSize: (row) => (row.isSonnet ? 13 : 11.5),
      fontWeight: (row) => (row.isSonnet ? 800 : 600)
    }),
    Plot.text(callouts, {
      x: 'x',
      y: 'y',
      text: 'text',
      dx: 20,
      dy: -22,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: 'color',
      fontSize: 18,
      fontWeight: 850
    })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID,
    '--plot-axis': AXIS,
    color: INK,
    fontSize: 13
  }
})

await finalizeToPng(chart, {
  title: 'How fresh is its knowledge?',
  subtitle: `Months from training cutoff to release · Sonnet 5’s ${formatGap(sonnet.gapMonths)} gap is middle-of-the-pack`,
  yCaption: 'Recent frontier models, sorted by release date',
  out: resolve(OUT_DIR, 'knowledge_freshness.png')
})
