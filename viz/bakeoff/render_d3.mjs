import { Database } from 'bun:sqlite'
import * as d3 from 'd3'
import { JSDOM } from 'jsdom'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const WIDTH = 1600
const HEIGHT = 900
const margin = { top: 80, right: 200, bottom: 50, left: 70 }
const innerWidth = WIDTH - margin.left - margin.right
const innerHeight = HEIGHT - margin.top - margin.bottom

const scriptDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(scriptDir, '../..')
const dbPath = resolve(scriptDir, '../../db/modeldb.sqlite')
const svgPath = resolve(scriptDir, 'd3.svg')
const pngPath = resolve(scriptDir, 'd3.png')

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

function colorForDeveloper(developerId) {
  return brandColors.get(String(developerId ?? '').toLowerCase()) ?? '#888888'
}

function labelFromSlug(slug) {
  return String(slug).split('/').pop()
}

function buildSeries(rawRows) {
  const bySlug = d3.group(
    rawRows.map((row) => ({
      slug: row.canonical_slug,
      developer_id: row.developer_id,
      date: new Date(`${row.measured_at}T00:00:00Z`),
      score: Number(row.score),
      short: labelFromSlug(row.canonical_slug)
    })),
    (row) => row.slug
  )

  return [...bySlug.entries()]
    .map(([slug, points]) => ({
      slug,
      developer_id: points[0]?.developer_id,
      short: points[0]?.short ?? slug,
      points: points.toSorted((a, b) => a.date - b.date)
    }))
    .filter((series) => series.points.length >= 8)
    .map((series) => ({ ...series, latest: series.points.at(-1) }))
    .sort((a, b) => b.latest.score - a.latest.score)
    .slice(0, 12)
    .map(({ latest: _latest, ...series }) => series)
}

function nudgedLabels(series, x, y) {
  const minimumGap = 21
  const labels = series
    .map((item) => {
      const last = item.points.at(-1)
      return {
        slug: item.slug,
        short: item.short,
        developer_id: item.developer_id,
        color: colorForDeveloper(item.developer_id),
        sourceX: x(last.date),
        sourceY: y(last.score),
        x: innerWidth + 16,
        y: y(last.score)
      }
    })
    .sort((a, b) => a.y - b.y)

  for (let index = 1; index < labels.length; index += 1) {
    labels[index].y = Math.max(labels[index].y, labels[index - 1].y + minimumGap)
  }

  const overflow = labels.at(-1).y - innerHeight
  if (overflow > 0) {
    for (const label of labels) {
      label.y -= overflow
    }
    for (let index = labels.length - 2; index >= 0; index -= 1) {
      labels[index].y = Math.min(labels[index].y, labels[index + 1].y - minimumGap)
    }
  }

  const topOverflow = -labels[0].y
  if (topOverflow > 0) {
    for (const label of labels) {
      label.y += topOverflow
    }
  }

  return labels
}

const db = new Database(dbPath)
const rawRows = db.query(query).all()
db.close()

const series = buildSeries(rawRows)
const rows = series.flatMap((item) =>
  item.points.map((point) => ({
    ...point,
    color: colorForDeveloper(point.developer_id)
  }))
)

if (rows.length === 0) {
  throw new Error('No LMArena rows matched the renderer filters.')
}

const dateExtent = d3.extent(rows, (row) => row.date)
const scoreExtent = d3.extent(rows, (row) => row.score)
const x = d3.scaleTime().domain(dateExtent).range([0, innerWidth])
const yPadding = Math.max(18, (scoreExtent[1] - scoreExtent[0]) * 0.06)
const y = d3
  .scaleLinear()
  .domain([
    Math.floor((scoreExtent[0] - yPadding) / 25) * 25,
    Math.ceil((scoreExtent[1] + yPadding) / 25) * 25
  ])
  .nice()
  .range([innerHeight, 0])

const dom = new JSDOM('<!doctype html><body></body>')
const document = dom.window.document
const svg = d3
  .select(document.body)
  .append('svg')
  .attr('xmlns', 'http://www.w3.org/2000/svg')
  .attr('width', WIDTH)
  .attr('height', HEIGHT)
  .attr('viewBox', `0 0 ${WIDTH} ${HEIGHT}`)
  .attr('aria-label', 'The LMArena ELO race')
  .attr('role', 'img')

svg.append('rect').attr('width', WIDTH).attr('height', HEIGHT).attr('fill', '#fbfcff')

svg
  .append('text')
  .attr('x', margin.left)
  .attr('y', 42)
  .attr('font-family', 'Helvetica, Arial, sans-serif')
  .attr('font-size', 24)
  .attr('font-weight', 700)
  .attr('fill', '#111827')
  .text('The LMArena ELO race')

svg
  .append('text')
  .attr('x', margin.left)
  .attr('y', 66)
  .attr('font-family', 'Helvetica, Arial, sans-serif')
  .attr('font-size', 14)
  .attr('fill', '#6b7280')
  .text('Text Overall · best variant per model per day · Source: LMArena')

const plot = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

plot
  .append('g')
  .attr('class', 'grid')
  .call(d3.axisLeft(y).ticks(8).tickSize(-innerWidth).tickFormat(''))
  .call((group) => group.select('.domain').remove())
  .call((group) => group.selectAll('line').attr('stroke', '#e6eaf0').attr('stroke-width', 1))
  .call((group) => group.selectAll('text').remove())

plot
  .append('g')
  .attr('transform', `translate(0,${innerHeight})`)
  .call(d3.axisBottom(x).ticks(d3.utcMonth.every(3)).tickFormat(d3.utcFormat('%Y-%m')))
  .call((group) => group.select('.domain').attr('stroke', '#d7dce4'))
  .call((group) => group.selectAll('line').attr('stroke', '#d7dce4'))
  .call((group) =>
    group
      .selectAll('text')
      .attr('font-family', 'Helvetica, Arial, sans-serif')
      .attr('font-size', 12)
      .attr('fill', '#697386')
      .attr('dy', '1.1em')
  )

plot
  .append('g')
  .call(d3.axisLeft(y).ticks(8).tickSize(0).tickPadding(10))
  .call((group) => group.select('.domain').remove())
  .call((group) =>
    group
      .selectAll('text')
      .attr('font-family', 'Helvetica, Arial, sans-serif')
      .attr('font-size', 12)
      .attr('fill', '#697386')
  )

plot
  .append('text')
  .attr('x', 0)
  .attr('y', -14)
  .attr('font-family', 'Helvetica, Arial, sans-serif')
  .attr('font-size', 12)
  .attr('font-weight', 600)
  .attr('fill', '#9aa4b2')
  .text('ELO score')

const line = d3
  .line()
  .defined((row) => Number.isFinite(row.score))
  .x((row) => x(row.date))
  .y((row) => y(row.score))
  .curve(d3.curveCatmullRom.alpha(0.35))

plot
  .append('g')
  .attr('fill', 'none')
  .selectAll('path')
  .data(series)
  .join('path')
  .attr('d', (item) => line(item.points))
  .attr('stroke', (item) => colorForDeveloper(item.developer_id))
  .attr('stroke-width', 2.5)
  .attr('stroke-linecap', 'round')
  .attr('stroke-linejoin', 'round')
  .attr('opacity', 0.94)

const labels = nudgedLabels(series, x, y)

const labelGroup = plot
  .append('g')
  .attr('font-family', 'Helvetica, Arial, sans-serif')
  .attr('font-size', 13)
  .attr('font-weight', 600)

labelGroup
  .selectAll('path')
  .data(labels)
  .join('path')
  .attr(
    'd',
    (label) =>
      `M${label.sourceX + 3},${label.sourceY} C${label.sourceX + 26},${label.sourceY} ${innerWidth - 8},${label.y} ${innerWidth + 10},${label.y}`
  )
  .attr('fill', 'none')
  .attr('stroke', (label) => label.color)
  .attr('stroke-opacity', 0.24)
  .attr('stroke-width', 1.1)

labelGroup
  .selectAll('text')
  .data(labels)
  .join('text')
  .attr('x', (label) => label.x)
  .attr('y', (label) => label.y)
  .attr('dy', '0.32em')
  .attr('fill', (label) => label.color)
  .text((label) => label.short)

plot
  .append('g')
  .selectAll('circle')
  .data(
    series.map((item) => ({ ...item.points.at(-1), color: colorForDeveloper(item.developer_id) }))
  )
  .join('circle')
  .attr('cx', (row) => x(row.date))
  .attr('cy', (row) => y(row.score))
  .attr('r', 4.5)
  .attr('fill', (row) => row.color)
  .attr('stroke', '#fbfcff')
  .attr('stroke-width', 2)

const svgText = svg.node().outerHTML
await Bun.write(svgPath, svgText)

const convert = Bun.spawnSync(
  ['rsvg-convert', '-w', '1600', '-h', '900', 'viz/bakeoff/d3.svg', '-o', 'viz/bakeoff/d3.png'],
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

const bytes = (await pngFile.arrayBuffer()).byteLength
console.log(`${pngPath} ${bytes} bytes`)
