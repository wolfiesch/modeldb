// Shared render + data plumbing for Observable Plot charts.
// Fixes the bake-off's driver quirks in ONE place: bun:sqlite opened without
// the readonly flag (readonly fails to attach the WAL sidecar on this DB), and
// a proven jsdom -> SVG -> rsvg-convert -> PNG pipeline with a title block.

import { Database } from 'bun:sqlite'
import { JSDOM } from 'jsdom'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { WIDTH, HEIGHT, FONT, INK, MUTED, FAINT } from './theme.mjs'

const libDir = dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = resolve(libDir, '../..')
export const DB_PATH = resolve(REPO_ROOT, 'db/modeldb.sqlite')
export const OUT_DIR = resolve(REPO_ROOT, 'viz/out')
// Resolve rsvg-convert cross-platform without shell probes (Windows-safe):
// env override -> Bun.which on PATH -> existence-checked common install paths.
function resolveRsvg() {
  const fromEnv = Bun.env.RSVG_CONVERT
  if (fromEnv) {
    return fromEnv
  }
  for (const name of ['rsvg-convert', 'rsvg-convert.exe']) {
    const found = Bun.which?.(name)
    if (found) {
      return found
    }
  }
  for (const candidate of [
    '/opt/homebrew/bin/rsvg-convert', // Apple Silicon Homebrew
    '/usr/local/bin/rsvg-convert', // Intel Homebrew / manual
    '/usr/bin/rsvg-convert' // Linux distro packages
  ]) {
    if (Bun.file(candidate).size > 0) {
      return candidate
    }
  }
  throw new Error(
    'rsvg-convert not found. Install it (macOS: `brew install librsvg`, ' +
      'Debian/Ubuntu: `apt install librsvg2-bin`, Windows: via MSYS2/scoop) ' +
      'or set RSVG_CONVERT to its path.'
  )
}
const SVG_NS = 'http://www.w3.org/2000/svg'

// Query the DB and return plain row objects. One place owns DB access.
export function queryRows(sql, params = []) {
  const db = new Database(DB_PATH) // NOT {readonly:true} — see module header
  try {
    return db.query(sql).all(...params)
  } finally {
    db.close()
  }
}

export function newDocument() {
  return new JSDOM('').window.document
}

// Extract the <svg> from a Plot.plot() result (may be an <svg> or a <figure>).
function extractSvg(chart) {
  return chart.matches?.('svg') ? chart : chart.querySelector('svg')
}

// Prepend a white background + title/subtitle/caption block onto a Plot SVG,
// serialize, run rsvg-convert. Returns the output byte length.
export async function finalizeToPng(chart, { title, subtitle, yCaption, out }) {
  const document = chart.ownerDocument
  const svg = extractSvg(chart)
  if (!svg) {
    throw new Error('Plot did not return an SVG element.')
  }

  svg.setAttribute('viewBox', `0 0 ${WIDTH} ${HEIGHT}`)
  if (title) {
    svg.setAttribute('aria-label', title)
  }

  const bg = document.createElementNS(SVG_NS, 'rect')
  bg.setAttribute('width', String(WIDTH))
  bg.setAttribute('height', String(HEIGHT))
  bg.setAttribute('fill', '#ffffff')
  svg.insertBefore(bg, svg.firstChild)

  const group = document.createElementNS(SVG_NS, 'g')
  group.setAttribute('font-family', FONT)
  group.setAttribute('text-anchor', 'start')
  const mk = (x, y, fill, size, weight, content) => {
    const t = document.createElementNS(SVG_NS, 'text')
    t.setAttribute('x', String(x))
    t.setAttribute('y', String(y))
    t.setAttribute('fill', fill)
    t.setAttribute('font-size', String(size))
    t.setAttribute('font-weight', String(weight))
    t.textContent = content
    return t
  }
  if (title) {
    group.append(mk(72, 46, INK, 34, 760, title))
  }
  if (subtitle) {
    group.append(mk(72, 78, MUTED, 17, 450, subtitle))
  }
  if (yCaption) {
    group.append(mk(72, 112, FAINT, 13, 520, yCaption))
  }
  svg.insertBefore(group, bg.nextSibling)

  let svgText = svg.outerHTML.replaceAll('currentColor', INK)
  const svgPath = out.replace(/\.png$/, '.svg')
  await Bun.write(svgPath, svgText)

  const convert = Bun.spawnSync(
    [resolveRsvg(), '-w', String(WIDTH), '-h', String(HEIGHT), svgPath, '-o', out],
    { cwd: REPO_ROOT, stdout: 'pipe', stderr: 'pipe' }
  )
  if (!convert.success) {
    throw new Error(`rsvg-convert failed: ${new TextDecoder().decode(convert.stderr)}`)
  }
  const file = Bun.file(out)
  if (!(await file.exists())) {
    throw new Error(`PNG not written: ${out}`)
  }
  const bytes = (await file.arrayBuffer()).byteLength
  console.log(`${out} ${bytes} bytes`)
  return bytes
}
