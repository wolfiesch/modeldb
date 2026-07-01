import { Database } from 'bun:sqlite'
import * as Plot from '@observablehq/plot'
import { JSDOM } from 'jsdom'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const WIDTH = 1600
const HEIGHT = 900
const MS_PER_DAY = 24 * 60 * 60 * 1000

const scriptDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(scriptDir, '../..')
const dbPath = resolve(repoRoot, 'db/modeldb.sqlite')
const outDir = resolve(repoRoot, 'viz/bakeoff')
const svgPath = resolve(outDir, 'observable.svg')
const pngPath = resolve(outDir, 'observable.png')

const brandColors = new Map([
  ['anthropic', '#d97757'],
  ['openai', '#10a37f'],
  ['google', '#4285f4'],
  ['xai', '#111111'],
  ['deepseek', '#4d6bfe'],
  ['zhipuai', '#c026d3'],
  ['moonshotai', '#16a34a'],
  ['alibaba', '#6b3fa0'],
  ['meta', '#0668e1']
])

const query = `
  SELECT br.model_id, m.canonical_slug, m.developer_id, br.measured_at, MAX(br.score) AS score
  FROM benchmark_result br JOIN model m ON m.id=br.model_id
  WHERE br.benchmark_id='lmarena_text_overall' AND br.model_id IS NOT NULL
  GROUP BY br.model_id, br.measured_at ORDER BY br.measured_at
`

function shortName(slug) {
  const name = String(slug).split('/').pop() ?? String(slug)
  return name
    .replace(/^claude-/, '')
    .replace(/^gemini-/, '')
    .replace(/^gpt-/, 'GPT-')
    .replace(/^o([0-9])/, 'o$1')
    .replace(/-/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function colorForDeveloper(developerId) {
  return brandColors.get(String(developerId ?? '').toLowerCase()) ?? '#888888'
}

function topSeries(rows) {
  const byModel = new Map()
  for (const row of rows) {
    const slug = row.canonical_slug
    const points = byModel.get(slug) ?? []
    points.push({
      model_id: row.model_id,
      slug,
      developer_id: row.developer_id,
      date: new Date(`${row.measured_at}T00:00:00Z`),
      score: Number(row.score),
      color: colorForDeveloper(row.developer_id),
      label: shortName(slug)
    })
    byModel.set(slug, points)
  }

  return [...byModel.values()]
    .filter((points) => points.length >= 8)
    .map((points) => points.sort((a, b) => a.date - b.date))
    .map((points) => ({ points, latest: points.at(-1) }))
    .sort((a, b) => b.latest.score - a.latest.score)
    .slice(0, 12)
    .map(({ points }) => points)
}

function adjustedLabels(series, labelDate, yMin, yMax) {
  const minimumGap = 19
  const scale = (HEIGHT - 170) / (yMax - yMin)
  const labels = series
    .map((points) => ({ ...points.at(-1), labelDate, labelScore: points.at(-1).score }))
    .sort((a, b) => b.score - a.score)

  for (let index = 1; index < labels.length; index += 1) {
    const previous = labels[index - 1]
    const current = labels[index]
    const pixelGap = (previous.labelScore - current.labelScore) * scale
    if (pixelGap < minimumGap) {
      current.labelScore = previous.labelScore - minimumGap / scale
    }
  }

  const bottomOverflow = yMin + 6 - labels.at(-1).labelScore
  if (bottomOverflow > 0) {
    for (const label of labels) {
      label.labelScore += bottomOverflow
    }
  }

  return labels.sort((a, b) => String(a.slug).localeCompare(String(b.slug)))
}

const db = new Database(dbPath, { readonly: true })
const rawRows = db.query(query).all()
db.close()

const series = topSeries(rawRows)
const rows = series.flat()
if (rows.length === 0) {
  throw new Error('No LMArena rows matched the renderer filters.')
}

const slugs = series.map((points) => points[0].slug)
const colors = series.map((points) => points[0].color)
const dates = rows.map((row) => row.date)
const scores = rows.map((row) => row.score)
const minDate = new Date(Math.min(...dates))
const maxDate = new Date(Math.max(...dates))
const labelDate = new Date(maxDate.getTime() + 22 * MS_PER_DAY)
const xMax = new Date(maxDate.getTime() + 115 * MS_PER_DAY)
const yMin = Math.floor((Math.min(...scores) - 20) / 25) * 25
const yMax = Math.ceil((Math.max(...scores) + 22) / 25) * 25
const labels = adjustedLabels(series, labelDate, yMin, yMax)

const document = new JSDOM('').window.document
const chart = Plot.plot({
  document,
  width: WIDTH,
  height: HEIGHT,
  marginTop: 104,
  marginRight: 238,
  marginBottom: 70,
  marginLeft: 72,
  x: {
    type: 'time',
    domain: [minDate, xMax],
    ticks: '3 months',
    tickSize: 0,
    tickPadding: 12,
    label: null
  },
  y: {
    domain: [yMin, yMax],
    grid: true,
    ticks: 8,
    tickSize: 0,
    tickPadding: 10,
    label: null
  },
  color: {
    domain: slugs,
    range: colors
  },
  marks: [
    Plot.ruleY([yMin], { stroke: '#d7dce4', strokeWidth: 1 }),
    Plot.line(rows, {
      x: 'date',
      y: 'score',
      z: 'slug',
      stroke: 'slug',
      strokeWidth: 3.2,
      strokeLinecap: 'round',
      strokeLinejoin: 'round',
      curve: 'catmull-rom'
    }),
    Plot.dot(
      series.map((points) => points.at(-1)),
      {
        x: 'date',
        y: 'score',
        fill: 'slug',
        stroke: '#ffffff',
        strokeWidth: 2.2,
        r: 5
      }
    ),
    Plot.link(labels, {
      x1: 'date',
      y1: 'score',
      x2: 'labelDate',
      y2: 'labelScore',
      stroke: 'slug',
      strokeOpacity: 0.34,
      strokeWidth: 1.2
    }),
    Plot.text(labels, {
      x: 'labelDate',
      y: 'labelScore',
      text: 'label',
      fill: 'slug',
      textAnchor: 'start',
      fontSize: 17,
      fontWeight: 650,
      lineAnchor: 'middle',
      dx: 8
    })
  ],
  style: {
    background: '#ffffff',
    color: '#1f2937',
    fontFamily: 'Inter, Helvetica, Arial, sans-serif',
    fontSize: 14
  }
})

const svg = chart.matches?.('svg') ? chart : chart.querySelector('svg')
if (!svg) {
  throw new Error('Observable Plot did not return an SVG element.')
}

svg.setAttribute('viewBox', `0 0 ${WIDTH} ${HEIGHT}`)
svg.setAttribute('aria-label', 'The LMArena ELO race')

const background = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
background.setAttribute('width', String(WIDTH))
background.setAttribute('height', String(HEIGHT))
background.setAttribute('fill', '#ffffff')
svg.insertBefore(background, svg.firstChild)

const titleGroup = document.createElementNS('http://www.w3.org/2000/svg', 'g')
titleGroup.setAttribute('font-family', 'Inter, Helvetica, Arial, sans-serif')
titleGroup.setAttribute('text-anchor', 'start')
const title = document.createElementNS('http://www.w3.org/2000/svg', 'text')
title.setAttribute('x', '72')
title.setAttribute('y', '46')
title.setAttribute('fill', '#101827')
title.setAttribute('font-size', '34')
title.setAttribute('font-weight', '760')
title.textContent = 'The LMArena ELO race'
const subtitle = document.createElementNS('http://www.w3.org/2000/svg', 'text')
subtitle.setAttribute('x', '72')
subtitle.setAttribute('y', '78')
subtitle.setAttribute('fill', '#64748b')
subtitle.setAttribute('font-size', '17')
subtitle.setAttribute('font-weight', '450')
subtitle.textContent = 'Text Overall · best variant per model per day · Source: LMArena'
const yLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text')
yLabel.setAttribute('x', '72')
yLabel.setAttribute('y', '112')
yLabel.setAttribute('fill', '#94a3b8')
yLabel.setAttribute('font-size', '13')
yLabel.setAttribute('font-weight', '520')
yLabel.textContent = 'Bradley–Terry rating'
titleGroup.append(title, subtitle, yLabel)
svg.insertBefore(titleGroup, background.nextSibling)

let svgText = svg.outerHTML
svgText = svgText.replaceAll('currentColor', '#1f2937')
await Bun.write(svgPath, svgText)

const convert = Bun.spawnSync(
  [
    '/opt/homebrew/bin/rsvg-convert',
    '-w',
    String(WIDTH),
    '-h',
    String(HEIGHT),
    svgPath,
    '-o',
    pngPath
  ],
  { cwd: repoRoot, stdout: 'pipe', stderr: 'pipe' }
)

if (!convert.success) {
  const stderr = new TextDecoder().decode(convert.stderr)
  throw new Error(`rsvg-convert failed: ${stderr}`)
}

const pngFile = Bun.file(pngPath)
if (!(await pngFile.exists())) {
  throw new Error(`Expected PNG was not written: ${pngPath}`)
}

console.log(`${pngPath} ${(await pngFile.arrayBuffer()).byteLength} bytes`)
