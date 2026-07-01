// The curated peer cohort — the single source of truth for "which models we compare".
// Hand-picked current-flagship set (2026-06), not an auto-filter, so the charts
// stay legible and every row is a name people recognize right now.
//
// To retune the story for a future launch: edit PEER_SLUGS. The hero is the
// launch model under the spotlight; peers are its direct rivals.
//
// Design notes:
//   - Slugs are CANONICAL first-party rows (not nvidia/inceptron mirror repos).
//   - resolvePeers() FAILS FAST if a slug is missing or matches >1 model row,
//     because this cohort is user-curated: a silent drop or mirror swap would
//     quietly break the story with no obvious render error.

import { queryRows } from './render.mjs'

export const HERO_SLUG = 'anthropic/claude-sonnet-5'

// Ordered: hero first, then rivals. Order is the default chart order.
export const PEER_SLUGS = [
  HERO_SLUG,
  'openai/gpt-5.5',
  'google/gemini-3.5-flash',
  'anthropic/claude-fable-5',
  'moonshotai/kimi-k2.7-code',
  'zhipuai/glm-5.2',
  'deepseek/deepseek-v4-pro'
]

// Resolve every peer slug to its model row. Throws on any missing/duplicate slug.
export function resolvePeers(slugs = PEER_SLUGS) {
  const seen = new Set()
  for (const slug of slugs) {
    if (seen.has(slug)) {
      throw new Error(`PEER_SET: duplicate slug in cohort: ${slug}`)
    }
    seen.add(slug)
  }
  const placeholders = slugs.map(() => '?').join(',')
  const rows = queryRows(
    `SELECT id, canonical_slug, developer_id, release_date, knowledge_cutoff
     FROM model WHERE canonical_slug IN (${placeholders})`,
    slugs
  )
  const bySlug = new Map()
  for (const row of rows) {
    if (bySlug.has(row.canonical_slug)) {
      throw new Error(`PEER_SET: slug matched >1 model row: ${row.canonical_slug}`)
    }
    bySlug.set(row.canonical_slug, row)
  }
  const missing = slugs.filter((slug) => !bySlug.has(slug))
  if (missing.length > 0) {
    throw new Error(`PEER_SET: ${missing.length} slug(s) not found in db: ${missing.join(', ')}`)
  }
  // Return in cohort order, tagging the hero.
  return slugs.map((slug) => ({ ...bySlug.get(slug), isHero: slug === HERO_SLUG }))
}

// Standard/base-tier price ($ per 1M tokens) for one model + component.
// tier_condition_json is null across the cohort, so we take the MODE of non-zero
// normalized values: MIN would return $0 cache/free-tier noise, MAX the
// long-context premium. Ties break to the lower (base) price. Returns null if none.
export function standardPrice(modelId, component, sourceId = 'models_dev') {
  const rows = queryRows(
    `SELECT normalized_usd_per_1m_tokens AS v FROM price_component
     WHERE model_id = ? AND source_id = ? AND component = ?
       AND normalized_usd_per_1m_tokens IS NOT NULL
       AND normalized_usd_per_1m_tokens > 0`,
    [modelId, sourceId, component]
  )
  if (rows.length === 0) {
    return null
  }
  const counts = new Map()
  for (const { v } of rows) {
    counts.set(v, (counts.get(v) ?? 0) + 1)
  }
  let best = null
  let bestCount = -1
  for (const [value, count] of counts) {
    if (count > bestCount || (count === bestCount && value < best)) {
      best = value
      bestCount = count
    }
  }
  return best
}
