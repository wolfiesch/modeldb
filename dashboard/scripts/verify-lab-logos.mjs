#!/usr/bin/env node

import { existsSync, readFileSync } from 'node:fs'
import { dirname, isAbsolute, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptsDir = dirname(fileURLToPath(import.meta.url))
const dashboardDir = resolve(scriptsDir, '..')
const modelsPath = resolve(dashboardDir, 'public/data/models.json')
const sourceManifestPath = resolve(dashboardDir, 'assets/lab-logos/labs.source.json')
const generatedManifestPath = resolve(dashboardDir, 'public/assets/labs/labs.generated.json')
const publicDir = resolve(dashboardDir, 'public')

const failures = []

function fail(message) {
  failures.push(message)
}

function readJson(path, label) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch (error) {
    fail(`${label}: unable to read or parse ${path}: ${error.message}`)
    return null
  }
}

function readText(path, label) {
  try {
    return readFileSync(path, 'utf8')
  } catch (error) {
    fail(`${label}: unable to read ${path}: ${error.message}`)
    return null
  }
}

function topLevelObjectKeys(raw, label) {
  const keys = []
  let depth = 0

  for (let index = 0; index < raw.length; index += 1) {
    const char = raw[index]

    if (char === '"') {
      const start = index
      index += 1
      for (; index < raw.length; index += 1) {
        if (raw[index] === '\\') {
          index += 1
          continue
        }
        if (raw[index] === '"') break
      }

      if (index >= raw.length) {
        fail(`${label}: unterminated string while scanning top-level keys`)
        return keys
      }

      if (depth === 1) {
        let cursor = index + 1
        while (/\s/.test(raw[cursor] ?? '')) cursor += 1
        if (raw[cursor] === ':') {
          try {
            keys.push(JSON.parse(raw.slice(start, index + 1)))
          } catch (error) {
            fail(`${label}: invalid top-level key at byte ${start}: ${error.message}`)
          }
        }
      }
      continue
    }

    if (char === '{' || char === '[') depth += 1
    else if (char === '}' || char === ']') depth -= 1
  }

  return keys
}

function duplicateCounts(values) {
  const counts = new Map()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  return [...counts.entries()].filter(([, count]) => count !== 1)
}

function compareExactSet(expected, actual, label) {
  const expectedSet = new Set(expected)
  const actualSet = new Set(actual)
  const missing = expected.filter((key) => !actualSet.has(key))
  const extra = actual.filter((key) => !expectedSet.has(key))

  if (missing.length > 0) fail(`${label}: missing dev keys: ${missing.join(', ')}`)
  if (extra.length > 0) fail(`${label}: unexpected dev keys: ${extra.join(', ')}`)
}

function publicAssetPath(markPath) {
  if (typeof markPath !== 'string' || markPath.length === 0) return null
  if (markPath.startsWith('/')) return resolve(publicDir, `.${markPath}`)
  if (isAbsolute(markPath)) return markPath
  return resolve(publicDir, markPath)
}

const models = readJson(modelsPath, 'models')
const sourceRaw = readText(sourceManifestPath, 'source manifest')
const generatedRaw = readText(generatedManifestPath, 'generated manifest')
const sourceManifest = sourceRaw ? readJson(sourceManifestPath, 'source manifest') : null
const generatedManifest = generatedRaw ? readJson(generatedManifestPath, 'generated manifest') : null

if (!Array.isArray(models)) {
  fail('models: expected dashboard/public/data/models.json to contain an array')
}

const devKeys = []
if (Array.isArray(models)) {
  models.forEach((model, index) => {
    if (!model || typeof model.dev !== 'string' || model.dev.length === 0) {
      fail(`models: model at index ${index} is missing a non-empty dev key`)
      return
    }
    if (!devKeys.includes(model.dev)) devKeys.push(model.dev)
  })
}

for (const [label, manifest, raw] of [
  ['source manifest', sourceManifest, sourceRaw],
  ['generated manifest', generatedManifest, generatedRaw],
]) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    fail(`${label}: expected a JSON object keyed by dev key`)
    continue
  }

  const parsedKeys = Object.keys(manifest)
  const scannedKeys = topLevelObjectKeys(raw, label)
  const duplicateKeys = duplicateCounts(scannedKeys)
  for (const [key, count] of duplicateKeys) fail(`${label}: dev key ${key} appears ${count} times`)

  compareExactSet(devKeys, parsedKeys, label)
}

if (generatedManifest && typeof generatedManifest === 'object' && !Array.isArray(generatedManifest)) {
  for (const devKey of Object.keys(generatedManifest)) {
    const entry = generatedManifest[devKey]
    const markPaths = [
      ['markPath', entry?.markPath ?? entry?.mark],
      ['markDarkPath', entry?.markDarkPath],
      ['markTilePath', entry?.markTilePath],
    ]
    for (const [field, markPath] of markPaths) {
      if (typeof markPath !== 'string' || markPath.length === 0) {
        fail(`generated manifest: ${devKey} is missing ${field}`)
        continue
      }

      const svgPath = publicAssetPath(markPath)
      if (!svgPath || !existsSync(svgPath)) {
        fail(`generated manifest: ${devKey} ${field} does not exist: ${markPath}`)
        continue
      }

      const svg = readText(svgPath, `${devKey} ${field} SVG`)
      if (!svg) continue
      if (!svg.trimStart().startsWith('<svg')) fail(`generated manifest: ${devKey} ${field} SVG does not start with <svg: ${markPath}`)
      if (!svg.includes('viewBox="0 0 100 100"')) {
        fail(`generated manifest: ${devKey} ${field} SVG missing viewBox="0 0 100 100": ${markPath}`)
      }
    }
  }
}

if (failures.length > 0) {
  for (const failure of failures) console.error(`verify-lab-logos: ${failure}`)
  process.exitCode = 1
} else {
  console.log(`verify-lab-logos: OK ${devKeys.length} dev keys, ${Object.keys(generatedManifest).length} generated logos`)
}
