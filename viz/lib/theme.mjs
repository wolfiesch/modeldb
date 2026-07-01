// Shared house style for all modeldb Observable Plot charts.
// One place to tune the whole visual identity — the agent edits here.

export const WIDTH = 1600
export const HEIGHT = 900
export const MS_PER_DAY = 24 * 60 * 60 * 1000

// Per-developer brand colors. Unknown developer -> NEUTRAL.
export const BRAND = new Map([
  ['anthropic', '#d97757'],
  ['openai', '#10a37f'],
  ['google', '#4285f4'],
  ['xai', '#111111'],
  ['deepseek', '#4d6bfe'],
  ['zhipuai', '#c026d3'],
  ['moonshotai', '#16a34a'],
  ['alibaba', '#6b3fa0'],
  ['meta', '#0668e1'],
  ['mistral', '#fd6f00'],
  ['cohere', '#39594d']
])
export const NEUTRAL = '#8b95a5'
export const HIGHLIGHT = '#e0245e' // launch/callout accent (also on-brand for X)

export const INK = '#101827' // titles
export const MUTED = '#64748b' // subtitles
export const FAINT = '#94a3b8' // axis captions
export const GRID = '#e6e9ef'
export const AXIS = '#d7dce4'

export const FONT = 'Inter, Helvetica, Arial, sans-serif'

export function colorFor(developerId) {
  return BRAND.get(String(developerId ?? '').toLowerCase()) ?? NEUTRAL
}

// Shared Plot `style` block so every chart has the same typographic base.
export const plotStyle = {
  background: '#ffffff',
  color: INK,
  fontFamily: FONT,
  fontSize: 14
}

// Turn a canonical slug into a compact display label.
export function shortName(slug) {
  let name = String(slug).split('/').pop() ?? String(slug)
  // Drop trailing snapshot dates: -20250929 or -2025-09-29.
  name = name.replace(/-\d{4}-?\d{2}-?\d{2}$/, '')
  // Join adjacent version segments with dots: sonnet-4-5 -> sonnet-4.5.
  name = name.replace(/(\d)-(\d)/g, '$1.$2')
  // Anthropic names read tier-first: claude-3-haiku -> Haiku 3, sonnet-4.5 -> Sonnet 4.5.
  name = name.replace(
    /^claude-(\d+(?:\.\d+)?)-(haiku|sonnet|opus)/i,
    (_, gen, tier) => `${tier}-${gen}`
  )
  name = name
    .replace(/^claude-/, '')
    .replace(/^gemini-/, '')
    .replace(/^gpt-/, 'GPT-')
    .replace(/-/g, ' ')
    .replace(/\b([a-z])/g, (letter) => letter.toUpperCase())
    .trim()
  // Restore brand/acronym casing the title-case pass flattened.
  const BRAND_CASING = [
    [/\bGlm\b/g, 'GLM'],
    [/\bDeepseek\b/g, 'DeepSeek'],
    [/\bKimi K2\b/g, 'Kimi K2'],
    [/\bMimo\b/g, 'MiMo'],
    [/\bQwq\b/g, 'QwQ'],
    [/\bLlama\b/g, 'Llama']
  ]
  for (const [pattern, replacement] of BRAND_CASING) {
    name = name.replace(pattern, replacement)
  }
  return name
}
