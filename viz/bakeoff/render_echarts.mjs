import * as echarts from 'echarts'
import { execSync, execSync as sh } from 'node:child_process'
import { statSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const WIDTH = 1600
const HEIGHT = 900
const MS_PER_DAY = 24 * 60 * 60 * 1000

const scriptDir = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(scriptDir, '../..')
const svgPath = resolve(repoRoot, 'viz/bakeoff/echarts.svg')
const pngPath = resolve(repoRoot, 'viz/bakeoff/echarts.png')

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

const pythonLoader = String.raw`
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

repo = Path.cwd()
db = repo / "db" / "modeldb.sqlite"
query = """
SELECT br.model_id, m.canonical_slug, m.developer_id, br.measured_at, MAX(br.score) AS score
FROM benchmark_result br JOIN model m ON m.id=br.model_id
WHERE br.benchmark_id='lmarena_text_overall' AND br.model_id IS NOT NULL
GROUP BY br.model_id, br.measured_at ORDER BY br.measured_at
"""

def short_name(slug):
    return str(slug).split('/')[-1]

with sqlite3.connect(db) as conn:
    rows = conn.execute(query).fetchall()

by_model = defaultdict(list)
metadata = {}
for model_id, slug, developer_id, measured_at, score in rows:
    by_model[model_id].append((measured_at, float(score)))
    metadata[model_id] = (slug, developer_id)

series = []
for model_id, points in by_model.items():
    if len(points) < 8:
        continue
    points.sort(key=lambda item: item[0])
    slug, developer_id = metadata[model_id]
    series.append({
        'model_id': model_id,
        'slug': slug,
        'developer_id': developer_id or '',
        'latest_score': points[-1][1],
        'points': points,
    })

series.sort(key=lambda item: item['latest_score'], reverse=True)
selected = series[:12]
flat = []
for item in selected:
    for measured_at, score in item['points']:
        flat.append({
            'slug': item['slug'],
            'developer_id': item['developer_id'],
            'date': measured_at,
            'score': score,
            'short_name': short_name(item['slug']),
        })
print(json.dumps(flat, separators=(',', ':')))
`

function colorForDeveloper(developerId) {
  return brandColors.get(String(developerId ?? '').toLowerCase()) ?? '#888888'
}

function loadRows() {
  const stdout = execSync('python3 -c "$PYTHON_LOADER"', {
    cwd: repoRoot,
    encoding: 'utf8',
    env: { ...process.env, PYTHON_LOADER: pythonLoader },
    maxBuffer: 8 * 1024 * 1024
  })
  const rows = JSON.parse(stdout)
  if (!Array.isArray(rows) || rows.length === 0) {
    throw new Error('No LMArena rows matched the renderer filters.')
  }
  return rows
}

function buildSeries(rows) {
  const bySlug = new Map()
  for (const row of rows) {
    const points = bySlug.get(row.slug) ?? []
    points.push(row)
    bySlug.set(row.slug, points)
  }

  return [...bySlug.values()].map((points) => {
    points.sort((a, b) => a.date.localeCompare(b.date))
    const first = points[0]
    const color = colorForDeveloper(first.developer_id)
    return {
      name: first.short_name,
      type: 'line',
      data: points.map((point) => [point.date, point.score]),
      showSymbol: false,
      smooth: false,
      z: 4,
      lineStyle: {
        color,
        width: 3.4,
        cap: 'round',
        join: 'round'
      },
      emphasis: {
        focus: 'series',
        lineStyle: { width: 4.5 }
      },
      endLabel: {
        show: true,
        formatter: first.short_name,
        color,
        fontFamily: 'Inter, Helvetica, Arial, sans-serif',
        fontSize: 17,
        fontWeight: 700,
        distance: 10,
        backgroundColor: 'rgba(255,255,255,0.72)',
        borderRadius: 3,
        padding: [2, 4]
      },
      labelLayout: {
        moveOverlap: 'shiftY'
      }
    }
  })
}

const rows = loadRows()
const series = buildSeries(rows)
const dates = rows.map((row) => row.date)
const scores = rows.map((row) => Number(row.score))
const minDate = new Date(
  `${dates.reduce((min, date) => (date < min ? date : min), dates[0])}T00:00:00Z`
)
const maxDate = new Date(
  `${dates.reduce((max, date) => (date > max ? date : max), dates[0])}T00:00:00Z`
)
const xMin = new Date(minDate.getTime() - 12 * MS_PER_DAY)
const xMax = new Date(maxDate.getTime() + 125 * MS_PER_DAY)
const yMin = Math.floor((Math.min(...scores) - 22) / 25) * 25
const yMax = Math.ceil((Math.max(...scores) + 26) / 25) * 25
const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: WIDTH, height: HEIGHT })

try {
  chart.setOption({
    animation: false,
    backgroundColor: '#ffffff',
    textStyle: {
      fontFamily: 'Inter, Helvetica, Arial, sans-serif',
      color: '#1f2937'
    },
    title: {
      left: 76,
      top: 36,
      text: 'The LMArena ELO race',
      subtext: 'Text Overall · best variant per model per day · Source: LMArena',
      textStyle: {
        color: '#101827',
        fontSize: 38,
        fontWeight: 800,
        lineHeight: 44
      },
      subtextStyle: {
        color: '#64748b',
        fontSize: 18,
        fontWeight: 450,
        lineHeight: 28
      },
      itemGap: 8
    },
    graphic: [
      {
        type: 'text',
        left: 78,
        top: 112,
        style: {
          text: 'Bradley–Terry rating',
          fill: '#94a3b8',
          font: '520 13px Inter, Helvetica, Arial, sans-serif'
        }
      }
    ],
    grid: {
      left: 82,
      right: 300,
      top: 142,
      bottom: 76,
      containLabel: false
    },
    xAxis: {
      type: 'time',
      min: xMin.toISOString().slice(0, 10),
      max: xMax.toISOString().slice(0, 10),
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#d1d5db' } },
      axisTick: { show: false },
      splitLine: { show: false },
      axisLabel: {
        color: '#64748b',
        fontSize: 14,
        margin: 16,
        formatter(value) {
          const date = new Date(value)
          const year = String(date.getUTCFullYear())
          const month = date.toLocaleString('en-US', { month: 'short', timeZone: 'UTC' })
          return date.getUTCMonth() === 0 ? year : month
        }
      },
      minInterval: 28 * MS_PER_DAY,
      maxInterval: 93 * MS_PER_DAY
    },
    yAxis: {
      type: 'value',
      scale: true,
      min: yMin,
      max: yMax,
      interval: 50,
      axisLine: { show: true, lineStyle: { color: '#d1d5db' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#64748b',
        fontSize: 14,
        margin: 12
      },
      splitLine: {
        show: true,
        lineStyle: { color: '#eeeeee', width: 1 }
      }
    },
    series
  })

  const svg = chart.renderToSVGString()
  writeFileSync(svgPath, svg)
  sh(
    `/opt/homebrew/bin/rsvg-convert -w ${WIDTH} -h ${HEIGHT} ${JSON.stringify(svgPath)} -o ${JSON.stringify(pngPath)}`,
    {
      cwd: repoRoot,
      stdio: 'pipe'
    }
  )
  const byteSize = statSync(pngPath).size
  console.log(`viz/bakeoff/echarts.png ${byteSize} bytes`)
} finally {
  chart.dispose()
}

process.exit(0)
