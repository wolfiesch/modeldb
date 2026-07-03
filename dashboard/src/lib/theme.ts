// Ported from viz/lib/theme.mjs — same values, TS translation.
import { labColorFor, labColorForDark } from './labs'

export const BRAND: Record<string, string> = {
  anthropic: '#d97757',
  openai: '#10a37f',
  google: '#4285f4',
  xai: '#111111',
  deepseek: '#4d6bfe',
  zhipuai: '#c026d3',
  moonshotai: '#16a34a',
  alibaba: '#6b3fa0',
  meta: '#0668e1',
  mistral: '#fd6f00',
  cohere: '#39594d',
}
export const NEUTRAL = '#8b95a5'
export const HIGHLIGHT = '#e0245e'

export const INK = '#101827'
export const MUTED = '#64748b'
export const FAINT = '#94a3b8'

export function colorFor(developerId: string | null | undefined): string {
  return labColorFor(developerId)
}

export function colorForDark(developerId: string | null | undefined): string {
  return labColorForDark(developerId)
}

export function shortName(slug: string): string {
  let name = String(slug).split('/').pop() ?? String(slug)
  name = name.replace(/-\d{4}-?\d{2}-?\d{2}$/, '')
  name = name.replace(/(\d)-(\d)(?!\d)/g, '$1.$2')
  name = name.replace(
    /^claude-(\d+(?:\.\d+)?)-(haiku|sonnet|opus)/i,
    (_, gen, tier) => `${tier}-${gen}`,
  )
  name = name
    .replace(/^claude-/, '')
    .replace(/^gpt-/, 'GPT-')
    .replace(/-/g, ' ')
    .replace(/\b([a-z])/g, (letter) => letter.toUpperCase())
    .trim()
  const BRAND_CASING: Array<[RegExp, string]> = [
    [/\bGlm\b/g, 'GLM'],
    [/\bDeepseek\b/g, 'DeepSeek'],
    [/\bKimi K2\b/g, 'Kimi K2'],
    [/\bMimo\b/g, 'MiMo'],
    [/\bQwq\b/g, 'QwQ'],
    [/\bLlama\b/g, 'Llama'],
    [/\bGemma\b/g, 'Gemma'],
    [/\bGemini\b/g, 'Gemini'],
    [/\bPalm\b/g, 'PaLM'],
    [/\b(\d+)m\b/gi, '$1M'],
    [/\b(\d+)b\b/gi, '$1B'],
  ]
  for (const [pattern, replacement] of BRAND_CASING) {
    name = name.replace(pattern, replacement)
  }
  return name
}
