import * as Plot from '@observablehq/plot'
import { resolve } from 'node:path'
import { newDocument, finalizeToPng, OUT_DIR } from './lib/render.mjs'
import { resolvePeers, HERO_SLUG } from './lib/peers.mjs'
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

function parseDate(value) {
  if (value === null || value === undefined || value === '') {
    return null
  }

  const text = String(value).trim()
  const match = text.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?$/)
  if (match) {
    const year = Number(match[1])
    const month = Number(match[2]) - 1
    const day = match[3] ? Number(match[3]) : 1
    return new Date(Date.UTC(year, month, day))
  }

  const date = new Date(text)
  if (Number.isNaN(date.getTime())) {
    throw new Error(`Invalid date value: ${text}`)
  }
  return date
}

function formatMonth(date) {
  return date.toLocaleDateString('en-US', {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC'
  })
}

function formatRelease(date) {
  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC'
  })
}

function formatGap(months) {
  return `${months.toFixed(1)} mo`
}

function toTimelineRow(row) {
  const cutoff = parseDate(row.knowledge_cutoff)
  const release = parseDate(row.release_date)
  if (!cutoff) {
    return null
  }
  if (!release) {
    throw new Error(`Missing release date for ${row.canonical_slug}`)
  }

  const gapDays = (release - cutoff) / MS_PER_DAY
  const gapMonths = gapDays / 30.44
  if (!Number.isFinite(gapMonths) || gapDays < 0) {
    throw new Error(`Invalid cutoff/release interval for ${row.canonical_slug}`)
  }

  const isHero = row.canonical_slug === HERO_SLUG
  const name = isHero ? 'Sonnet 5' : shortName(row.canonical_slug)
  const gapLabel = formatGap(gapMonths)

  return {
    ...row,
    cutoff,
    release,
    gapDays,
    gapMonths,
    isHero,
    name,
    rowLabel: `${name} · ${gapLabel}`,
    gapLabel,
    color: isHero ? HIGHLIGHT : colorFor(row.developer_id)
  }
}

const peers = resolvePeers()
const omitted = peers.filter((row) => !row.knowledge_cutoff)
const orderedRows = peers
  .map(toTimelineRow)
  .filter(Boolean)
  .sort((a, b) => b.release - a.release || a.gapMonths - b.gapMonths || a.name.localeCompare(b.name))

const sonnet = orderedRows.find((row) => row.isHero)
if (!sonnet) {
  throw new Error('Sonnet 5 knowledge freshness row missing from disclosed-cutoff peer cohort.')
}

if (orderedRows.length === 0) {
  throw new Error('No curated peer rows disclose a knowledge cutoff.')
}

const yDomain = orderedRows.map((row) => row.rowLabel)
const minCutoff = new Date(Math.min(...orderedRows.map((row) => row.cutoff.getTime())) - 35 * MS_PER_DAY)
const maxRelease = new Date(Math.max(...orderedRows.map((row) => row.release.getTime())) + 95 * MS_PER_DAY)
const labelX = new Date(minCutoff.getTime() + 2 * MS_PER_DAY)
const noteText =
  omitted.length > 0
    ? `cutoff not disclosed for ${omitted.map((row) => shortName(row.canonical_slug)).join(', ')}`
    : null
const subtitle =
  `Months from training cutoff to release · current flagships · Sonnet 5: Jan 2026 -> Jun 30 2026` +
  ` · ${Math.round(sonnet.gapMonths)} mo is typical${ 
  noteText ? ` · ${noteText}` : ''}`

const callouts = [
  {
    x: sonnet.release,
    y: sonnet.rowLabel,
    text: `Sonnet 5: ~${Math.round(sonnet.gapMonths)} mo · ${formatMonth(sonnet.cutoff)} -> ${formatRelease(sonnet.release)}`,
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
  marginLeft: 330,
  x: {
    domain: [minCutoff, maxRelease],
    grid: true,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  y: {
    domain: yDomain,
    axis: null,
    label: null
  },
  marks: [
    Plot.ruleY(yDomain, { stroke: GRID, strokeWidth: 0.8, strokeOpacity: 0.6 }),
    Plot.ruleX([sonnet.release], {
      stroke: HIGHLIGHT,
      strokeWidth: 1.4,
      strokeOpacity: 0.36,
      strokeDasharray: '4 5'
    }),
    Plot.link(
      orderedRows.filter((row) => !row.isHero),
      {
        x1: 'cutoff',
        x2: 'release',
        y1: 'rowLabel',
        y2: 'rowLabel',
        stroke: (row) => row.color,
        strokeWidth: 8,
        strokeOpacity: 0.54,
        strokeLinecap: 'round'
      }
    ),
    Plot.link(
      orderedRows.filter((row) => row.isHero),
      {
        x1: 'cutoff',
        x2: 'release',
        y1: 'rowLabel',
        y2: 'rowLabel',
        stroke: HIGHLIGHT,
        strokeWidth: 13,
        strokeOpacity: 0.98,
        strokeLinecap: 'round'
      }
    ),
    Plot.dot(orderedRows, {
      x: 'cutoff',
      y: 'rowLabel',
      r: (row) => (row.isHero ? 6.2 : 4.4),
      fill: '#ffffff',
      stroke: (row) => row.color,
      strokeWidth: (row) => (row.isHero ? 3 : 1.8)
    }),
    Plot.dot(orderedRows, {
      x: 'release',
      y: 'rowLabel',
      r: (row) => (row.isHero ? 9 : 6),
      fill: (row) => row.color,
      fillOpacity: (row) => (row.isHero ? 1 : 0.9),
      stroke: '#ffffff',
      strokeWidth: (row) => (row.isHero ? 2.8 : 1.4)
    }),
    Plot.text(orderedRows, {
      x: labelX,
      y: 'rowLabel',
      text: 'rowLabel',
      dx: -14,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fill: (row) => (row.isHero ? HIGHLIGHT : INK),
      fontSize: (row) => (row.isHero ? 22 : 18),
      fontWeight: (row) => (row.isHero ? 850 : 650)
    }),
    Plot.text(orderedRows, {
      x: 'cutoff',
      y: 'rowLabel',
      text: (row) => formatMonth(row.cutoff),
      dx: -12,
      dy: -18,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fill: (row) => (row.isHero ? HIGHLIGHT : MUTED),
      fontSize: (row) => (row.isHero ? 13 : 11.5),
      fontWeight: (row) => (row.isHero ? 800 : 600)
    }),
    Plot.text(orderedRows, {
      x: 'release',
      y: 'rowLabel',
      text: (row) => formatRelease(row.release),
      dx: 12,
      dy: 18,
      textAnchor: 'start',
      lineAnchor: 'middle',
      fill: (row) => (row.isHero ? HIGHLIGHT : MUTED),
      fontSize: (row) => (row.isHero ? 13 : 11.5),
      fontWeight: (row) => (row.isHero ? 800 : 600)
    }),
    Plot.text(callouts, {
      x: 'x',
      y: 'y',
      text: 'text',
      dx: -8,
      dy: -34,
      textAnchor: 'end',
      lineAnchor: 'middle',
      fill: 'color',
      fontSize: 20,
      fontWeight: 850
    })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID,
    '--plot-axis': AXIS,
    color: INK,
    fontSize: 14
  }
})

await finalizeToPng(chart, {
  title: 'How fresh is its knowledge?',
  subtitle,
  yCaption: 'Curated current-flagship cohort, sorted by release date',
  out: resolve(OUT_DIR, 'knowledge_freshness.png')
})
