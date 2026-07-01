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
  NEUTRAL
} from './lib/theme.mjs'

const SONNET_5_ID = 75
const ONE_MILLION = 1_000_000

const SQL = `
SELECT
  m.id,
  m.canonical_slug AS slug,
  m.developer_id AS developer,
  MAX(CASE WHEN mc.capability='context_window' THEN CAST(mc.value AS INTEGER) END) AS context_window,
  MAX(CASE WHEN mc.capability='max_output' THEN CAST(mc.value AS INTEGER) END) AS max_output
FROM model m
JOIN model_capability mc
  ON mc.model_id=m.id
  AND mc.capability IN ('context_window', 'max_output')
GROUP BY m.id, m.canonical_slug, m.developer_id
HAVING context_window IS NOT NULL AND max_output IS NOT NULL
`

function formatTokens(value) {
  if (value >= 1_000_000) {
    const millions = value / 1_000_000
    return `${Number.isInteger(millions) ? millions : millions.toFixed(2)}M`
  }
  if (value >= 1_000) {
    const thousands = value / 1_000
    return `${Number.isInteger(thousands) ? thousands : thousands.toFixed(0)}K`
  }
  return String(value)
}

function labelFor(slug) {
  return shortName(slug)
    .replace(/^MiniMax /, '')
    .replace(/^Mimo /, 'MiMo ')
    .replace(/^Mistral Large Latest$/, 'Mistral Large')
    .replace(/^Qwen3 Coder Plus$/, 'Qwen Coder+')
    .replace(/^Gemini 2\.5 Pro$/, 'Gemini 2.5 Pro')
    .replace(/^Deepseek V4 Pro$/, 'DeepSeek V4 Pro')
}

const Y_DOMAIN = [3_800, 1_180_000]

function declutterLabelColumn(labels) {
  const minPixelGap = 30
  const plotHeight = HEIGHT - 104 - 68
  const logMin = Math.log10(Y_DOMAIN[0])
  const logMax = Math.log10(Y_DOMAIN[1])
  const minGap = (minPixelGap / plotHeight) * (logMax - logMin)
  const bottomPad = (12 / plotHeight) * (logMax - logMin)
  const grouped = Map.groupBy(
    labels.map((label, index) => ({ ...label, originalIndex: index, logY: Math.log10(label.labelY) })),
    (label) => label.anchor
  )

  for (const group of grouped.values()) {
    group.sort((a, b) => b.logY - a.logY)
    for (let index = 1; index < group.length; index += 1) {
      const gap = group[index - 1].logY - group[index].logY
      if (gap < minGap) {
        group[index].logY = group[index - 1].logY - minGap
      }
    }

    const bottomOverflow = logMin + bottomPad - group.at(-1).logY
    if (bottomOverflow > 0) {
      for (const label of group) {
        label.logY += bottomOverflow
      }
    }
  }

  return [...grouped.values()]
    .flat()
    .sort((a, b) => a.originalIndex - b.originalIndex)
    .map(({ originalIndex: _originalIndex, logY, ...label }) => ({ ...label, labelY: 10 ** logY }))
}


const points = queryRows(SQL).map((row) => ({
  id: row.id,
  slug: row.slug,
  developer: row.developer,
  context_window: row.context_window,
  max_output: row.max_output,
  color: colorFor(row.developer),
  label: labelFor(row.slug),
  isSonnet5: row.id === SONNET_5_ID
}))

if (points.length === 0) {
  throw new Error('No models with both context_window and max_output capabilities.')
}

const sonnet5 = points.find((point) => point.isSonnet5)
if (!sonnet5) {
  throw new Error('Sonnet 5 capability row not found.')
}

const clubAtOrAbove = points.filter((point) => point.context_window >= ONE_MILLION).length
const clubExact = points.filter((point) => point.context_window === ONE_MILLION).length

const labelOverrides = new Map([
  [
    'anthropic/claude-sonnet-5',
    { labelX: 1_115_000, labelY: 176_000, anchor: 'start', dx: 12, dy: 0, weight: 850 }
  ],
  ['sakana/fugu-ultra', { labelX: 760_000, labelY: 890_000, anchor: 'end', dx: -8, dy: 0 }],
  ['xai/grok-4.3', { labelX: 1_115_000, labelY: 820_000, anchor: 'start', dx: 8, dy: 2 }],
  ['minimax/MiniMax-M3', { labelX: 1_115_000, labelY: 520_000, anchor: 'start', dx: 8, dy: 0 }],
  ['deepseek/deepseek-v4-pro', { labelX: 815_000, labelY: 405_000, anchor: 'end', dx: -8, dy: 2 }],
  [
    'nvidia/nvidia/nemotron-3-super-120b-a12b',
    { labelX: 800_000, labelY: 250_000, anchor: 'end', dx: -8, dy: 3, label: 'Nemotron 3 Super' }
  ],
  ['xiaomi/mimo-v2-pro', { labelX: 1_115_000, labelY: 270_000, anchor: 'start', dx: 8, dy: -2 }],
  ['openai/gpt-5-pro', { labelX: 335_000, labelY: 310_000, anchor: 'end', dx: -8, dy: -1 }],
  ['google/gemini-2.5-pro', { labelX: 1_115_000, labelY: 58_000, anchor: 'start', dx: 8, dy: -2 }],
  ['alibaba/qwen3-coder-plus', { labelX: 790_000, labelY: 63_000, anchor: 'end', dx: -8, dy: 7 }]
])

const labels = declutterLabelColumn(
  [...labelOverrides.entries()]
    .map(([slug, override]) => {
      const point = points.find((candidate) => candidate.slug === slug)
      if (!point) {return null}
      return {
        ...point,
        label: override.label ?? point.label,
        labelX: override.labelX,
        labelY: override.labelY,
        anchor: override.anchor,
        dx: override.dx,
        dy: override.dy,
        weight: override.weight ?? 650
      }
    })
    .filter(Boolean)
)

const sonnetLabel = labels.find((point) => point.isSonnet5)
const otherLabels = labels.filter((point) => !point.isSonnet5)
const referenceNotes = [
  { x: 760_000, y: 22_000, text: '1M-token club', weight: 800, dy: 0 },
  { x: 760_000, y: 16_500, text: `${clubExact} exactly · ${clubAtOrAbove} at/above`, weight: 500, dy: 0 }
]

const chart = Plot.plot({
  document: newDocument(),
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 150,
  marginBottom: 68,
  marginLeft: 82,
  x: {
    type: 'log',
    domain: [3_800, 1_230_000],
    grid: true,
    ticks: [4_000, 8_000, 16_000, 32_000, 64_000, 128_000, 256_000, 512_000, 1_000_000],
    tickFormat: formatTokens,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  y: {
    type: 'log',
    domain: Y_DOMAIN,
    grid: true,
    ticks: [4_000, 8_000, 16_000, 32_000, 64_000, 128_000, 256_000, 512_000, 1_000_000],
    tickFormat: formatTokens,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  marks: [
    Plot.ruleY([4_000], { stroke: AXIS, strokeWidth: 1 }),
    Plot.ruleX([ONE_MILLION], {
      stroke: HIGHLIGHT,
      strokeOpacity: 0.36,
      strokeWidth: 2,
      strokeDasharray: '6 6'
    }),
    Plot.dot(
      points.filter((point) => !point.isSonnet5),
      {
        x: 'context_window',
        y: 'max_output',
        r: 4.5,
        fill: (point) => point.color,
        fillOpacity: 0.42,
        stroke: '#ffffff',
        strokeOpacity: 0.7,
        strokeWidth: 0.7
      }
    ),
    Plot.link(otherLabels, {
      x1: 'context_window',
      y1: 'max_output',
      x2: 'labelX',
      y2: 'labelY',
      stroke: (point) => point.color,
      strokeOpacity: 0.28,
      strokeWidth: 1
    }),
    Plot.link([sonnetLabel], {
      x1: 'context_window',
      y1: 'max_output',
      x2: 'labelX',
      y2: 'labelY',
      stroke: HIGHLIGHT,
      strokeOpacity: 0.68,
      strokeWidth: 1.8
    }),
    Plot.dot([sonnet5], {
      x: 'context_window',
      y: 'max_output',
      r: 13,
      fill: HIGHLIGHT,
      fillOpacity: 0.96,
      stroke: '#111111',
      strokeWidth: 1.6
    }),
    Plot.text(otherLabels, {
      x: 'labelX',
      y: 'labelY',
      text: 'label',
      fill: (point) => point.color,
      dx: 'dx',
      dy: 'dy',
      textAnchor: 'anchor',
      lineAnchor: 'middle',
      fontSize: 12,
      fontWeight: 'weight'
    }),
    Plot.text([sonnetLabel], {
      x: 'labelX',
      y: 'labelY',
      text: () => 'Sonnet 5',
      fill: HIGHLIGHT,
      dx: 'dx',
      dy: -14,
      textAnchor: 'anchor',
      lineAnchor: 'bottom',
      fontSize: 19,
      fontWeight: 850
    }),
    Plot.text([sonnetLabel], {
      x: 'labelX',
      y: 'labelY',
      text: () => '1M in · 128K out',
      fill: INK,
      dx: 'dx',
      dy: 8,
      textAnchor: 'anchor',
      lineAnchor: 'top',
      fontSize: 13,
      fontWeight: 650
    }),
    Plot.text(referenceNotes, {
      x: 'x',
      y: 'y',
      text: 'text',
      fill: (point, index) => (index === 0 ? HIGHLIGHT : MUTED),
      textAnchor: 'end',
      lineAnchor: 'middle',
      fontSize: (point, index) => (index === 0 ? 15 : 12),
      fontWeight: 'weight'
    })
  ],
  style: {
    ...plotStyle,
    '--plot-background': '#ffffff',
    '--plot-grid': GRID,
    '--plot-axis': AXIS,
    color: NEUTRAL
  }
})

await finalizeToPng(chart, {
  title: 'The 1M-token club',
  subtitle: 'Context window vs max output tokens · Sonnet 5: 1M in, 128K out',
  yCaption: 'Max output tokens',
  out: resolve(OUT_DIR, 'context_frontier.png')
})
