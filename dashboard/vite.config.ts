import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { ROUTE_META, SITE_ORIGIN, type RouteMeta } from './src/lib/routeMeta.ts'

function escapeAttribute(value: string): string {
  return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;')
}

function replaceOnce(html: string, pattern: RegExp, replacement: string): string {
  const matches = html.match(new RegExp(pattern.source, 'g'))
  if (matches?.length !== 1) {
    throw new Error(`route-meta-pages: expected one match for ${pattern} in index.html`)
  }
  return html.replace(pattern, replacement)
}

function renderRouteHtml(html: string, path: string, meta: RouteMeta): string {
  const title = escapeAttribute(meta.title)
  const description = escapeAttribute(meta.description)
  const url = `${SITE_ORIGIN}${path}`
  let out = replaceOnce(html, /<title>[^<]*<\/title>/, `<title>${title}</title>\n    <link rel="canonical" href="${url}" />`)
  out = replaceOnce(out, /<meta\s+name="description"\s+content="[^"]*"\s*\/>/, `<meta name="description" content="${description}" />`)
  out = replaceOnce(out, /<meta\s+property="og:title"\s+content="[^"]*"\s*\/>/, `<meta property="og:title" content="${title}" />`)
  out = replaceOnce(
    out,
    /<meta\s+property="og:description"\s+content="[^"]*"\s*\/>/,
    `<meta property="og:description" content="${description}" />`,
  )
  return replaceOnce(out, /<meta\s+property="og:url"\s+content="[^"]*"\s*\/>/, `<meta property="og:url" content="${url}" />`)
}

// The dashboard is client-rendered, so crawlers only see index.html. Emit a
// copy per ROUTE_META entry with that route's title, description, and
// canonical URL at `<path>/index.html`.
function routeMetaPages(): Plugin {
  return {
    name: 'route-meta-pages',
    apply: 'build',
    enforce: 'post',
    generateBundle: {
      order: 'post',
      handler(_, bundle) {
        const index = bundle['index.html']
        if (index?.type !== 'asset' || typeof index.source !== 'string') {
          throw new Error('route-meta-pages: index.html missing from bundle')
        }
        for (const [path, meta] of Object.entries(ROUTE_META)) {
          this.emitFile({
            type: 'asset',
            fileName: `${path.slice(1)}/index.html`,
            source: renderRouteHtml(index.source, path, meta),
          })
        }
      },
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), routeMetaPages()],
  base: '/',
  build: { outDir: 'dist' },
})
