#!/usr/bin/env node

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptsDir = dirname(fileURLToPath(import.meta.url))
const dashboardDir = resolve(scriptsDir, '..')
const generatedManifestPath = resolve(dashboardDir, 'public/assets/labs/labs.generated.json')
const outDir = resolve(dashboardDir, 'tmp')
const outPath = resolve(outDir, 'lab-logo-contact-sheet.html')
const sizes = [16, 24, 32, 48]
const backgrounds = [
  { key: 'light', label: 'Light', className: 'swatch-light' },
  { key: 'dark', label: 'Dark', className: 'swatch-dark' },
]

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function markPathFor(entry) {
  return entry?.markPath ?? entry?.mark
}

const generatedManifest = JSON.parse(readFileSync(generatedManifestPath, 'utf8'))
const labs = Object.entries(generatedManifest).map(([devKey, entry]) => ({
  devKey,
  label: entry.label ?? devKey,
  markPath: markPathFor(entry),
  status: entry.status ?? 'unknown',
}))

const rows = labs
  .map((lab) => {
    const previews = backgrounds
      .map(
        (background) => `
          <section class="preview-group ${background.className}" aria-label="${escapeHtml(lab.label)} on ${background.label.toLowerCase()} background">
            <div class="preview-label">${background.label}</div>
            <div class="sizes">
              ${sizes
                .map(
                  (size) => `
                    <figure class="logo-size">
                      <div class="logo-frame" style="--logo-size: ${size}px">
                        <img src="${escapeHtml(lab.markPath)}" width="${size}" height="${size}" alt="${escapeHtml(lab.label)} logo at ${size}px" loading="lazy">
                      </div>
                      <figcaption>${size}px</figcaption>
                    </figure>`,
                )
                .join('')}
            </div>
          </section>`,
      )
      .join('')

    return `
      <article class="lab-card">
        <header>
          <h2>${escapeHtml(lab.label)}</h2>
          <p><code>${escapeHtml(lab.devKey)}</code> · ${escapeHtml(lab.status)}</p>
        </header>
        <div class="previews">${previews}</div>
      </article>`
  })
  .join('')

const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Lab Logo Contact Sheet</title>
  <style>
    :root {
      color-scheme: light dark;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f4f5f7;
      color: #14161a;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      padding: 32px;
      background: #f4f5f7;
      color: #14161a;
    }

    main {
      max-width: 1440px;
      margin: 0 auto;
    }

    h1 {
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: -0.03em;
    }

    .summary {
      margin: 0 0 24px;
      color: #5d6575;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
      gap: 16px;
    }

    .lab-card {
      border: 1px solid #d8dde7;
      border-radius: 18px;
      background: #ffffff;
      box-shadow: 0 1px 2px rgba(20, 22, 26, 0.05);
      overflow: hidden;
    }

    .lab-card header {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px 12px;
      border-bottom: 1px solid #e8ebf0;
    }

    .lab-card h2 {
      margin: 0;
      font-size: 17px;
      letter-spacing: -0.02em;
    }

    .lab-card p {
      margin: 0;
      color: #6c7482;
      font-size: 12px;
      white-space: nowrap;
    }

    .previews {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 0;
    }

    .preview-group {
      min-width: 0;
      padding: 14px;
    }

    .preview-group + .preview-group {
      border-left: 1px solid #e8ebf0;
    }

    .swatch-light {
      background: #f8fafc;
      color: #14161a;
    }

    .swatch-dark {
      background: #101318;
      color: #eef2f7;
    }

    .preview-label {
      margin-bottom: 10px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      opacity: 0.72;
    }

    .sizes {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      align-items: end;
      gap: 10px;
    }

    .logo-size {
      display: grid;
      justify-items: center;
      gap: 8px;
      margin: 0;
    }

    .logo-frame {
      display: grid;
      place-items: center;
      width: 56px;
      height: 56px;
      border-radius: 12px;
      outline: 1px solid rgba(127, 140, 160, 0.25);
    }

    .logo-frame img {
      display: block;
      width: var(--logo-size);
      height: var(--logo-size);
    }

    figcaption {
      font-size: 11px;
      opacity: 0.7;
    }
  </style>
</head>
<body>
  <main>
    <h1>Lab Logo Contact Sheet</h1>
    <p class="summary">${labs.length} generated lab logos shown at ${sizes.join(', ')}px on dark and light backgrounds.</p>
    <section class="grid" aria-label="Generated lab logo previews">
      ${rows}
    </section>
  </main>
</body>
</html>
`

mkdirSync(outDir, { recursive: true })
writeFileSync(outPath, html)
console.log(`render-lab-logo-contact-sheet: wrote ${outPath}`)
